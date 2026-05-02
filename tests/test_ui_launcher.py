"""Regression tests for desktop UI launcher wiring (packaging/size related)."""

from __future__ import annotations

import sys
import types

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
