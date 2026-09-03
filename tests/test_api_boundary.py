from fastapi.middleware.cors import CORSMiddleware

from alac_rip.server import app


def test_cors_is_limited_to_the_desktop_webview_and_local_dev():
    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)

    assert cors.kwargs["allow_origins"] == ["http://tauri.localhost", "http://localhost:1420"]
    assert cors.kwargs["allow_methods"] == ["GET", "POST", "PATCH", "PUT", "DELETE"]
    assert cors.kwargs["allow_headers"] == ["content-type", "x-pies-api-token"]
