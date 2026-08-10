"""Async runtime and lifecycle coverage for backend entrypoint."""

from __future__ import annotations

import asyncio

import app.core.config as config_mod
import app.db.mongo as mongo_mod
import app.main as main_mod


def test_effective_reload_is_guarded_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("UVICORN_RELOAD", "true")
    monkeypatch.setenv("JWT_ACCESS_SECRET", "prod-access-secret-value")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "prod-refresh-secret-value")
    config_mod.get_settings.cache_clear()
    settings = config_mod.get_settings()
    assert settings.uvicorn_reload is True
    assert settings.effective_uvicorn_reload is False


def test_mongo_lifecycle_updates_health_signal() -> None:
    asyncio.run(mongo_mod.init_mongo())
    connected = mongo_mod.mongo_health_signal()
    assert connected["enabled"] is True
    assert connected["connected"] is True
    assert connected["status"] == "connected"

    asyncio.run(mongo_mod.close_mongo())
    closed = mongo_mod.mongo_health_signal()
    assert closed["connected"] is False
    assert closed["status"] in {"closed", "disabled"}


def test_serve_uses_uvicorn_config_and_runtime_overrides(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "8123")
    monkeypatch.setenv("UVICORN_RELOAD", "true")
    monkeypatch.setenv("UVICORN_WORKERS", "3")
    monkeypatch.setenv("JWT_ACCESS_SECRET", "prod-access-secret-value")
    monkeypatch.setenv("JWT_REFRESH_SECRET", "prod-refresh-secret-value")
    config_mod.get_settings.cache_clear()

    captured: dict[str, object] = {}

    class FakeServer:
        def __init__(self, cfg):
            captured["config"] = cfg

        async def serve(self) -> None:
            return None

    monkeypatch.setattr(main_mod, "Server", FakeServer)
    asyncio.run(main_mod.serve())

    cfg = captured["config"]
    assert getattr(cfg, "host") == "127.0.0.1"
    assert getattr(cfg, "port") == 8123
    assert getattr(cfg, "reload") is False
    assert getattr(cfg, "workers") == 3


def test_run_handles_keyboard_interrupt_without_raising(monkeypatch) -> None:
    async def _interrupting_serve() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_mod, "serve", _interrupting_serve)
    main_mod.run()
