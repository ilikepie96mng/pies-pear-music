import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_tauri_conf_metadata():
    tauri_conf_path = REPO_ROOT / "app" / "src-tauri" / "tauri.conf.json"
    assert tauri_conf_path.exists(), "tauri.conf.json not found"

    with open(tauri_conf_path, "r", encoding="utf-8") as f:
        conf = json.load(f)

    assert conf.get("productName") == "Pies Pear Music"
    assert conf.get("identifier") == "com.pies.pear-music"
    assert conf.get("mainBinaryName") == "pies-pear-music"

    bundle = conf.get("bundle", {})
    assert bundle.get("category") == "Music"
    assert "binaries/pies-backend" in bundle.get("externalBin", [])

    icons = bundle.get("icon", [])
    assert len(icons) > 0
    for icon in icons:
        icon_file = REPO_ROOT / "app" / "src-tauri" / icon
        assert icon_file.exists(), f"Icon referenced in tauri.conf.json does not exist: {icon_file}"


def test_tauri_capabilities_permissions():
    cap_path = REPO_ROOT / "app" / "src-tauri" / "capabilities" / "default.json"
    assert cap_path.exists(), "default.json capability file not found"

    with open(cap_path, "r", encoding="utf-8") as f:
        cap = json.load(f)

    permissions = cap.get("permissions", [])
    flat_perms = [p if isinstance(p, str) else p.get("identifier") for p in permissions]

    assert "core:default" in flat_perms
    assert "dialog:default" in flat_perms
    assert "opener:default" in flat_perms
    assert "notification:default" in flat_perms

    # Ensure shell allow-spawn includes backend sidecar
    sidecar_allowed = False
    for p in permissions:
        if isinstance(p, dict) and p.get("identifier") == "shell:allow-spawn":
            for allowed in p.get("allow", []):
                if allowed.get("name") == "binaries/pies-backend" and allowed.get("sidecar") is True:
                    sidecar_allowed = True
    assert sidecar_allowed, "Sidecar spawn permission missing in default.json capabilities"


def test_cargo_manifest_notification_plugin():
    cargo_path = REPO_ROOT / "app" / "src-tauri" / "Cargo.toml"
    assert cargo_path.exists()
    content = cargo_path.read_text(encoding="utf-8")
    assert 'tauri-plugin-notification = "2"' in content
    assert 'name = "pies-pear-music"' in content


def test_notifications_typescript_definitions():
    ts_path = REPO_ROOT / "app" / "src" / "lib" / "notifications.ts"
    assert ts_path.exists(), "notifications.ts does not exist"
    content = ts_path.read_text(encoding="utf-8")

    assert "notifySyncStarted" in content
    assert "notifySyncCompleted" in content
    assert "notifySyncFailed" in content
    assert "notifyIntegrityCompleted" in content
    assert "notifyDapExportCompleted" in content
    assert "@tauri-apps/plugin-notification" in content


def test_packaging_scripts_exist_and_executable():
    scripts = [
        "scripts/build-packages.sh",
        "scripts/verify-packaging.sh",
        "scripts/build-backend-sidecar.sh",
        "scripts/verify-package-contents.sh",
    ]
    for script_rel in scripts:
        script_path = REPO_ROOT / script_rel
        assert script_path.exists(), f"Script missing: {script_rel}"
        assert (script_path.stat().st_mode & 0o111) != 0, f"Script not executable: {script_rel}"


def test_sidecar_binary_ready_if_present():
    sidecar_bin = REPO_ROOT / "app" / "src-tauri" / "binaries" / "pies-backend-x86_64-unknown-linux-gnu"
    if sidecar_bin.exists():
        assert (sidecar_bin.stat().st_mode & 0o111) != 0, "Sidecar binary is not executable"
