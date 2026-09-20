import pytest

import alac_rip.server as server
from alac_rip.config import Config


class FakePipe:
    def __init__(self, lines: list[str]):
        self._lines = iter(lines)
        self.closed = False

    def readline(self) -> str:
        return next(self._lines, "")

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, stdout: FakePipe | None = None, exit_code: int | None = None):
        self.stdout = stdout or FakePipe([])
        self.stdin = self
        self.exit_code = exit_code
        self.writes: list[str] = []
        self.terminated = False

    def poll(self) -> int | None:
        return self.exit_code

    def write(self, value: str) -> None:
        self.writes.append(value)

    def flush(self) -> None:
        pass

    def terminate(self) -> None:
        self.terminated = True


from collections import deque


@pytest.fixture(autouse=True)
def reset_wrapper_state(monkeypatch):
    monkeypatch.setattr(server, "wrapper_process", None)
    monkeypatch.setattr(server, "wrapper_running", False)
    monkeypatch.setattr(server, "wrapper_needs_2fa", False)
    monkeypatch.setattr(server, "wrapper_2fa_type", "")
    monkeypatch.setattr(server, "wrapper_logs", deque(maxlen=200))
    monkeypatch.setattr(server, "_session_credentials", None)



def test_sms_2fa_contract_uses_the_existing_wrapper_marker():
    pipe = FakePipe(["credentialHandler: 2FA: true\n"])
    logs: list[str] = []

    server.stream_wrapper_logs(pipe, logs)

    assert server.wrapper_needs_2fa is True
    assert server.wrapper_2fa_type == "sms"
    assert "2FA required — please enter your code" in logs
    assert pipe.closed is True


def test_trusted_device_2fa_contract_uses_the_existing_wrapper_marker():
    pipe = FakePipe(["[.] response type 4\n"])
    logs: list[str] = []

    server.stream_wrapper_logs(pipe, logs)

    assert server.wrapper_needs_2fa is True
    assert server.wrapper_2fa_type == "device"
    assert "2FA required — Apple sent a code to your trusted device" in logs


def test_success_contract_marks_wrapper_ready_and_persists_only_after_success(monkeypatch):
    pipe = FakePipe(["[.] response type 6\n"])
    logs: list[str] = []
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(server, "save_credentials", lambda email, password: stored.append((email, password)) or True)

    server.stream_wrapper_logs(pipe, logs, "contract@example.invalid", "synthetic-password")

    assert server.wrapper_running is True
    assert server.wrapper_needs_2fa is False
    assert stored == [("contract@example.invalid", "synthetic-password")]
    assert "Login successful. Ready for downloads." in logs


def test_failed_auto_login_contract_removes_the_saved_credential_reference(monkeypatch):
    process = FakeProcess(exit_code=1)
    deleted: list[bool] = []
    monkeypatch.setattr(server, "wrapper_process", process)
    monkeypatch.setattr(server, "delete_credentials", lambda: deleted.append(True))

    server.stream_wrapper_logs(FakePipe([]), [], auto_login=True)

    assert deleted == [True]
    assert server.wrapper_running is False


def test_wrapper_logs_redact_submitted_credentials_without_changing_marker_parsing():
    email = "contract@example.invalid"
    password = "synthetic-password"
    logs: list[str] = []

    server.stream_wrapper_logs(
        FakePipe([f"wrapper saw {email} and {password}; [.] response type 6\n"]),
        logs,
        email,
        password,
    )

    assert server.wrapper_running is True
    assert all(email not in entry and password not in entry for entry in logs)
    assert any("[.] response type 6" in entry for entry in logs)


def test_login_command_shape_is_frozen_by_contract(monkeypatch, tmp_path):
    wrapper_dir = tmp_path / "tools" / "wrapper"
    wrapper_dir.mkdir(parents=True)
    monkeypatch.setattr(server, "cfg", Config(
        music_dir=tmp_path / "music",
        state_dir=tmp_path / "state",
        alac_rip_dir=wrapper_dir.parent,
    ))
    monkeypatch.setattr(server, "ensure_wrapper_image", lambda _dir: (True, None))
    monkeypatch.setattr(server, "save_credentials", lambda _email, _password: True)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: None)

    captured_cmd: list[list[str]] = []
    captured_env: list[dict] = []
    process = FakeProcess(FakePipe(["[.] response type 6\n"]))
    monkeypatch.setattr(
        server.subprocess,
        "Popen",
        lambda command, **kwargs: captured_cmd.append(command) or captured_env.append(kwargs.get("env", {})) or process,
    )

    class InlineThread:
        def __init__(self, *, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(server.threading, "Thread", InlineThread)

    assert server.start_wrapper_login("contract@example.invalid", "synthetic-password") is True
    assert len(captured_cmd) == 1
    cmd = captured_cmd[0]
    assert cmd == [
        "podman", "run", "--rm", "--name", server.CONTAINER_NAME, "-i",
        "--network", "host", "--volume", "/dev/urandom:/app/rootfs/dev/urandom:ro",
        server.IMAGE_NAME,
    ]
    assert "--env-file" not in cmd
    assert "args" not in captured_env[0]
    assert server.wrapper_running is True


def test_shutdown_contract_terminates_the_active_wrapper_once(monkeypatch):
    process = FakeProcess()
    monkeypatch.setattr(server, "wrapper_process", process)
    monkeypatch.setattr(server, "wrapper_running", True)
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: None)

    result = server.stop_wrapper()

    assert result == {"status": "ok", "msg": "Wrapper stopped"}
    assert process.terminated is True
    assert server.wrapper_running is False


def test_restart_wrapper_reauthenticates_with_saved_credentials(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "load_credentials", lambda: ("contract@example.invalid", "synthetic-password"))
    monkeypatch.setattr(
        server,
        "start_wrapper_login",
        lambda email, password, auto_login: calls.append((email, password, auto_login)) or True,
    )
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: None)

    result = server.restart_wrapper()

    assert result == {"status": "ok", "msg": "Reconnecting with saved credentials..."}
    assert calls == [("contract@example.invalid", "synthetic-password", True)]


def test_logout_wrapper_stops_and_deletes_credentials(monkeypatch):
    process = FakeProcess()
    monkeypatch.setattr(server, "wrapper_process", process)
    monkeypatch.setattr(server, "wrapper_running", True)
    deleted = []
    monkeypatch.setattr(server, "delete_credentials", lambda: deleted.append(True))
    monkeypatch.setattr(server.subprocess, "run", lambda *args, **kwargs: None)

    result = server.logout_wrapper()

    assert result == {"status": "ok", "msg": "Logged out successfully"}
    assert process.terminated is True
    assert server.wrapper_running is False
    assert deleted == [True]


def test_2fa_code_contract_writes_one_newline_terminated_value():
    process = FakeProcess()
    server.wrapper_process = process
    server.wrapper_needs_2fa = True
    server.wrapper_2fa_type = "sms"

    result = server.submit_2fa(server.TwoFARequest(code="123456"))

    assert result == {"status": "ok", "msg": "2FA code submitted"}
    assert process.writes == ["123456\n"]
    assert server.wrapper_needs_2fa is False
    assert server.wrapper_2fa_type == ""


def test_restart_contract_delegates_saved_credentials_to_auto_login(monkeypatch):
    calls: list[tuple[str, str, bool]] = []
    monkeypatch.setattr(server, "load_credentials", lambda: ("contract@example.invalid", "synthetic-password"))
    monkeypatch.setattr(
        server,
        "start_wrapper_login",
        lambda email, password, auto_login: calls.append((email, password, auto_login)) or True,
    )

    assert server.attempt_auto_login() is True
    assert calls == [("contract@example.invalid", "synthetic-password", True)]


def test_secret_service_contract_stores_json_and_cleans_up_legacy_file(monkeypatch, tmp_path):
    legacy = tmp_path / ".credentials"
    legacy.write_text("legacy credential data")
    calls: list[tuple[list[str], str]] = []
    monkeypatch.setattr(server, "_credentials_path", lambda: legacy)
    monkeypatch.setattr(server, "_secret_service_available", lambda: True)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs["input"]))
        or server.subprocess.CompletedProcess(command, 0, "", ""),
    )

    assert server.save_credentials("contract@example.invalid", "synthetic-password") is True

    assert calls == [(
        ["secret-tool", "store", f"--label={server._SECRET_SERVICE_LABEL}", *server._SECRET_SERVICE_ATTRIBUTES],
        '{"email": "contract@example.invalid", "password": "synthetic-password"}',
    )]
    assert legacy.exists() is False
    assert server.load_credentials() == ("contract@example.invalid", "synthetic-password")


def test_session_only_contract_never_creates_a_file_when_secret_service_is_unavailable(monkeypatch, tmp_path):
    legacy = tmp_path / ".credentials"
    monkeypatch.setattr(server, "_credentials_path", lambda: legacy)
    monkeypatch.setattr(server, "_secret_service_available", lambda: False)

    assert server.save_credentials("contract@example.invalid", "synthetic-password") is False

    assert server.load_credentials() == ("contract@example.invalid", "synthetic-password")
    assert legacy.exists() is False


def test_secret_service_load_and_clear_contract(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    legacy = tmp_path / ".credentials"
    legacy.write_text("legacy credential data")
    monkeypatch.setattr(server, "_credentials_path", lambda: legacy)
    monkeypatch.setattr(server, "_secret_service_available", lambda: True)

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[1] == "lookup":
            return server.subprocess.CompletedProcess(
                command, 0, '{"email": "contract@example.invalid", "password": "synthetic-password"}', "",
            )
        return server.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server.load_credentials() == ("contract@example.invalid", "synthetic-password")
    server.delete_credentials()

    assert calls == [
        ["secret-tool", "lookup", *server._SECRET_SERVICE_ATTRIBUTES],
        ["secret-tool", "clear", *server._SECRET_SERVICE_ATTRIBUTES],
    ]
    assert legacy.exists() is False


def test_malformed_secret_service_data_fails_closed(monkeypatch):
    monkeypatch.setattr(server, "_secret_service_available", lambda: True)
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda command, **kwargs: server.subprocess.CompletedProcess(command, 0, "[]", ""),
    )

    assert server.load_credentials() == (None, None)
