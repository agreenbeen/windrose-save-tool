"""Regression tests for desktop UI launcher wiring (packaging/size related)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_ui_window_does_not_force_qt_backend():
    """Qt/PySide6 was removed from the bundle; launcher must use platform defaults."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "r5_save_tool" / "ui_window.py"
    text = src.read_text(encoding="utf-8")
    assert 'gui="qt"' not in text
    assert "gui='qt'" not in text


def test_launch_calls_webview_start_without_gui_kwarg(monkeypatch):
    """Native path must not pass gui= (avoids Qt); only debug= is set explicitly."""
    start_kwargs: dict[str, object] = {}

    def start(**kwargs: object) -> None:
        start_kwargs.update(kwargs)

    fake = types.SimpleNamespace(
        create_window=lambda *a, **k: None,
        start=start,
    )
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr("r5_save_tool.ui_window._wait_for_api", lambda timeout=20.0: True)

    def exit_raises(code: int = 0) -> None:
        raise SystemExit(code)

    monkeypatch.setattr("r5_save_tool.ui_window.sys.exit", exit_raises)

    from r5_save_tool.ui_window import launch

    with pytest.raises(SystemExit) as exc_info:
        launch()
    assert exc_info.value.code == 0
    assert "gui" not in start_kwargs
    assert start_kwargs.get("debug") is False


def test_fallback_chromium_app_mode_triggers_api_teardown(monkeypatch, tmp_path: Path) -> None:
    """When webview fails, Edge/Chrome app mode runs; closing the shell should stop uvicorn."""
    import r5_save_tool.ui_window as uw

    port = 29876
    monkeypatch.setattr(uw, "API_PORT", port, raising=False)
    monkeypatch.setattr(uw, "API_URL", f"http://127.0.0.1:{port}/ui/", raising=False)
    monkeypatch.setattr(uw, "HEALTH_URL", f"http://127.0.0.1:{port}/api/health", raising=False)

    def wait_api(timeout: float = uw.STARTUP_TIMEOUT) -> bool:
        if abs(timeout - 0.8) < 0.01:
            return False
        return True

    monkeypatch.setattr(uw, "_wait_for_api", wait_api)
    monkeypatch.setattr(uw, "_port_in_use", lambda h, p: False)
    monkeypatch.setattr(uw, "_is_frozen_bundle", lambda: False)

    proc = MagicMock()
    proc.poll.return_value = 0
    profile = tmp_path / "appmode-profile"
    profile.mkdir()
    monkeypatch.setattr(
        uw,
        "_try_start_chromium_app_mode",
        lambda url: (proc, profile),
    )

    fake_webview = types.SimpleNamespace(
        create_window=lambda *a, **k: None,
        start=lambda **k: (_ for _ in ()).throw(RuntimeError("no webview")),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    stopped: list[tuple[object, object, object]] = []
    real_stop = uw._stop_api_backend

    def spy_stop(s: object, th: object, ch: object) -> None:
        stopped.append((s, th, ch))
        real_stop(s, th, ch)

    monkeypatch.setattr(uw, "_stop_api_backend", spy_stop)

    uw.launch()
    assert len(stopped) == 1
    assert stopped[0][0] is not None
    assert stopped[0][1] is not None
    assert stopped[0][2] is None
    assert not profile.exists()


def test_main_internal_server_env_calls_uvicorn(monkeypatch) -> None:
    import r5_save_tool.ui_window as uw

    monkeypatch.setenv(uw._INTERNAL_SERVER_ENV, "1")
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*a: object, **k: object) -> None:
        calls.append((a, k))

    monkeypatch.setattr(uw, "uvicorn", types.SimpleNamespace(run=fake_run))
    uw.main()
    assert len(calls) == 1
    args, kw = calls[0]
    assert args[0] == "r5_save_tool.ui_api:app"
    assert kw["host"] == uw.API_HOST
    assert kw["port"] == uw.API_PORT


def test_frozen_gui_bootstraps_stdio_when_streams_missing(monkeypatch) -> None:
    import r5_save_tool.ui_window as uw

    monkeypatch.setattr(uw, "_is_frozen_bundle", lambda: True)
    monkeypatch.setattr(uw.sys, "stdout", None)
    monkeypatch.setattr(uw.sys, "stderr", None)
    uw._ensure_stdio_for_frozen_gui()
    assert uw.sys.stdout is not None
    assert uw.sys.stderr is not None
    uw.sys.stdout.write("ok\n")
    uw.sys.stderr.write("ok\n")


def test_ephemeral_port_auto_updates_urls(monkeypatch) -> None:
    import r5_save_tool.ui_window as uw

    monkeypatch.setenv("R5_SAVE_UI_PORT", "auto")
    uw._maybe_assign_ephemeral_ui_port()
    assert uw.API_PORT > 0
    assert str(uw.API_PORT) in uw.API_URL
    assert str(uw.API_PORT) in uw.HEALTH_URL
    assert os.environ["R5_SAVE_UI_PORT"] == str(uw.API_PORT)


def test_uvicorn_listen_host_frozen_windows_binds_all_interfaces(monkeypatch) -> None:
    import r5_save_tool.ui_window as uw

    monkeypatch.delenv("R5_SAVE_UI_BIND", raising=False)
    monkeypatch.setattr(uw, "_is_frozen_bundle", lambda: True)
    monkeypatch.setattr(uw.sys, "platform", "win32")
    assert uw._uvicorn_listen_host() == "0.0.0.0"
    monkeypatch.setenv("R5_SAVE_UI_BIND", "127.0.0.1")
    assert uw._uvicorn_listen_host() == "127.0.0.1"


def test_uvicorn_listen_host_not_frozen_uses_api_host(monkeypatch) -> None:
    import r5_save_tool.ui_window as uw

    monkeypatch.delenv("R5_SAVE_UI_BIND", raising=False)
    monkeypatch.setattr(uw, "_is_frozen_bundle", lambda: False)
    monkeypatch.setattr(uw, "API_HOST", "127.0.0.1", raising=False)
    assert uw._uvicorn_listen_host() == "127.0.0.1"


def test_health_payload_detection() -> None:
    from r5_save_tool.ui_window import _health_payload_is_windrose_api

    assert _health_payload_is_windrose_api(
        {"ok": True, "status": {"manifest_found": False, "doctor": None}}
    )
    assert not _health_payload_is_windrose_api({"ok": True, "status": {}})
    assert not _health_payload_is_windrose_api({"ok": True})
    assert not _health_payload_is_windrose_api({"ok": False, "status": {"manifest_found": True}})


def test_webview2_loopback_env_is_idempotent(monkeypatch) -> None:
    """WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS must allow http://127.0.0.1 from WebView2."""
    monkeypatch.delenv("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", raising=False)
    from r5_save_tool import ui_window as uw

    uw._ensure_webview2_can_reach_loopback()
    v = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    assert "BlockInsecurePrivateNetworkRequests" in v
    assert "allow-insecure-localhost" in v.lower()
    uw._ensure_webview2_can_reach_loopback()
    assert os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS") == v


def test_fallback_default_browser_when_no_chromium_shell(monkeypatch) -> None:
    """If no Edge/Chrome executable is available, fall back to default browser (reuse API)."""
    import r5_save_tool.ui_window as uw

    opened: list[str] = []
    monkeypatch.setattr(uw, "_wait_for_api", lambda timeout=20.0: True)
    monkeypatch.setattr(uw, "_try_start_chromium_app_mode", lambda url: (None, None))
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))

    fake_webview = types.SimpleNamespace(
        create_window=lambda *a, **k: None,
        start=lambda **k: (_ for _ in ()).throw(RuntimeError("no webview")),
    )
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    uw.launch()
    assert opened == [uw.API_URL]
