import asyncio

import pytest
from starlette.requests import Request
from starlette.responses import Response

import alac_rip.server as server


def _request(path: str, headers: list[tuple[bytes, bytes]] | None = None, method: str = "GET") -> Request:
    return Request({
        "type": "http",
        "method": method,
        "path": path.split("?", 1)[0],
        "query_string": path.partition("?")[2].encode(),
        "headers": headers or [],
    })


async def _ok(_: Request) -> Response:
    return Response(status_code=204)


def test_sidecar_capability_rejects_missing_wrong_or_url_token(monkeypatch):
    monkeypatch.setattr(server, "_api_capability", "fixture-capability")

    missing = asyncio.run(server.require_api_capability(_request("/health"), _ok))
    wrong = asyncio.run(server.require_api_capability(
        _request("/health", [(b"x-pies-api-token", b"wrong")]), _ok,
    ))
    url_token = asyncio.run(server.require_api_capability(
        _request("/health?capability=fixture-capability"), _ok,
    ))

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert url_token.status_code == 401


def test_sidecar_capability_accepts_the_header_token(monkeypatch):
    monkeypatch.setattr(server, "_api_capability", "fixture-capability")

    header = asyncio.run(server.require_api_capability(
        _request("/health", [(b"x-pies-api-token", b"fixture-capability")]), _ok,
    ))
    assert header.status_code == 204


def test_capability_is_disabled_only_for_direct_development_server(monkeypatch):
    monkeypatch.setattr(server, "_api_capability", None)

    response = asyncio.run(server.require_api_capability(_request("/health"), _ok))

    assert response.status_code == 204


def test_stdin_sidecar_handshake_requires_a_valid_port_and_capability():
    capability = "a" * 64

    assert server._read_sidecar_handshake(
        f'{{"port": 43129, "capability": "{capability}"}}',
    ) == (43129, capability)
    with pytest.raises(ValueError):
        server._read_sidecar_handshake('{"port": 0, "capability": "bad"}')
