"""
Desktop window launcher for Windrose Save Tool UI.

Starts the FastAPI server in a background daemon thread, waits for it to
become healthy, then opens a native desktop window via pywebview pointed at
the served frontend.

Usage:
    python -m r5_save_tool.ui_window
    r5-save-ui          (installed console script)
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

API_HOST = os.environ.get("R5_SAVE_UI_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("R5_SAVE_UI_PORT", "8765"))
API_URL = f"http://{API_HOST}:{API_PORT}/ui/"
HEALTH_URL = f"http://{API_HOST}:{API_PORT}/api/health"
WINDOW_TITLE = "Windrose Save Tool"
WINDOW_W, WINDOW_H = 1280, 820
STARTUP_TIMEOUT = 20.0


def _make_server() -> uvicorn.Server:
    # log_config=None disables uvicorn's default log formatter, which calls
    # sys.stdout.isatty() — crashing when stdout is None in a windowless EXE.
    config = uvicorn.Config(
        "r5_save_tool.ui_api:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_config=None,
        access_log=False,
    )
    return uvicorn.Server(config)


def _run_api(server: uvicorn.Server) -> None:
    """Run the FastAPI + uvicorn server in a thread."""
    server.run()


def _wait_for_api(timeout: float = STARTUP_TIMEOUT) -> bool:
    """Poll the health endpoint until the API responds or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def _port_in_use(host: str, port: int) -> bool:
    """Return True when a TCP listener is already bound to host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _stop_server(server: uvicorn.Server | None, thread: threading.Thread | None) -> None:
    """Request graceful server shutdown and wait briefly for thread exit."""
    if server is None or thread is None:
        return
    server.should_exit = True
    thread.join(timeout=5)


def launch() -> None:
    """
    Start the API then open a desktop window.

    Tries pywebview first (native window using the platform default — on
    Windows this is WebView2 / Edge Chromium, not Qt). If pywebview or its
    native backend is unavailable the tool falls back to the system browser.
    """
    started_local_api = False
    api_server: uvicorn.Server | None = None
    t: threading.Thread | None = None
    print(f"Starting Windrose Save Tool API on port {API_PORT}…", flush=True)

    # If another UI instance is already running, reuse it instead of failing.
    if _wait_for_api(timeout=0.8):
        print(f"ℹ  Reusing existing UI API on port {API_PORT}.", flush=True)
        ready = True
    else:
        # If something else owns the port, fail cleanly with guidance.
        if _port_in_use(API_HOST, API_PORT):
            print(
                f"⚠  Port {API_PORT} is already in use by another process.\n"
                "   Stop that process or set a different R5_SAVE_UI_PORT before launch.",
                flush=True,
            )
            sys.exit(1)

        api_server = _make_server()
        # Daemon thread is fine because we explicitly keep the process alive while needed.
        t = threading.Thread(target=_run_api, args=(api_server,), daemon=True)
        t.start()
        started_local_api = True
        ready = _wait_for_api()

    if not ready:
        print(f"⚠  API did not respond in time. Check that port {API_PORT} is free.", flush=True)
        _stop_server(api_server, t)
        sys.exit(1)

    try:
        import webview as _wv

        _wv.create_window(
            WINDOW_TITLE,
            url=API_URL,
            width=WINDOW_W,
            height=WINDOW_H,
            resizable=True,
            min_size=(900, 600),
        )
        # Default GUI backend keeps the bundle small (no PySide6). WebView2 is a system component.
        _wv.start(debug=False)
        # Native window closed.
        if started_local_api:
            _stop_server(api_server, t)
        sys.exit(0)
    except Exception as exc:
        # pywebview unavailable or backend missing; fall back to browser mode.
        import webbrowser

        print(
            f"ℹ  pywebview unavailable ({exc.__class__.__name__}: {exc}).\n"
            f"   Opening in system browser instead.\n"
            f"   URL: {API_URL}\n"
            f"   Press Ctrl+C to stop the server.",
            flush=True,
        )
        webbrowser.open(API_URL)

        # If we reused an existing API, this process can exit now.
        if not started_local_api:
            return

        # Keep the local API alive for browser mode until user interruption.
        try:
            while t is not None and t.is_alive():
                t.join(timeout=1)
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
        finally:
            _stop_server(api_server, t)


def main() -> None:
    launch()


if __name__ == "__main__":
    main()
