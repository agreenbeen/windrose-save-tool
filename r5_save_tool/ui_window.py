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

import asyncio
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

# When set, this process only runs uvicorn (spawned by the parent PyInstaller EXE).
_INTERNAL_SERVER_ENV = "R5_SAVE_UI_INTERNAL_SERVER"

API_HOST = os.environ.get("R5_SAVE_UI_HOST", "127.0.0.1")


def _port_env_token() -> str:
    return os.environ.get("R5_SAVE_UI_PORT", "8765").strip().lower()


def _initial_api_port_from_environ() -> int:
    """Default port at import; ``0`` / ``auto`` are resolved in ``launch()``."""
    tok = _port_env_token()
    if tok in ("0", "auto"):
        return 8765
    try:
        return int(os.environ.get("R5_SAVE_UI_PORT", "8765"))
    except ValueError:
        return 8765


API_PORT = _initial_api_port_from_environ()
API_URL = f"http://{API_HOST}:{API_PORT}/ui/"
HEALTH_URL = f"http://{API_HOST}:{API_PORT}/api/health"
WINDOW_TITLE = "Windrose Save Tool"
WINDOW_W, WINDOW_H = 1280, 820
STARTUP_TIMEOUT = 20.0

# Chromium / WebView2 may block http://127.0.0.1 from embedded contexts (private
# network access). Bundle several related disables; see WebView2Feedback #1950 / #4166.
_WEBVIEW2_LOOPBACK_ARGS = (
    "--disable-features=BlockInsecurePrivateNetworkRequests,"
    "PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults"
)
_EXTRA_PNA_DISABLE_FEATURES = (
    "BlockInsecurePrivateNetworkRequests,"
    "PrivateNetworkAccessSendPreflights,"
    "PrivateNetworkAccessRespectPreflightResults"
)

# The AppContainer that hosts the WebView2 renderer process.  Windows network
# isolation blocks loopback connections from inside AppContainers by default,
# so the renderer cannot reach 127.0.0.1 unless it is explicitly exempted.
_WEBVIEW2_APPCONTAINER = "microsoft.win32webviewhost_cw5n1h2txyewy"


def _ensure_webview2_can_reach_loopback() -> None:
    """Set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS before the WebView2 runtime starts."""
    key = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
    cur = os.environ.get(key, "").strip()
    low = cur.lower()
    need_pna = "blockinsecureprivatenetworkrequests" not in low
    need_localhost = "allow-insecure-localhost" not in low
    if not need_pna and not need_localhost:
        return
    parts = [cur] if cur else []
    if need_pna:
        parts.append(_WEBVIEW2_LOOPBACK_ARGS)
    if need_localhost:
        parts.append("--allow-insecure-localhost")
    os.environ[key] = " ".join(parts).strip()


def _append_loopback_flags_to_browser_args(current: str) -> str:
    """Merge loopback/PNA disables into pywebview's ``AdditionalBrowserArguments`` string.

    pywebview sets ``CreationProperties.AdditionalBrowserArguments`` itself (see
    ``edgechromium.py``), which overrides the ``WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS``
    env var for that control.  Flags must be appended on the same string.
    """
    out = (current or "").strip()
    if "allow-insecure-localhost" not in out.lower():
        out = f"{out} --allow-insecure-localhost".strip()
    if "blockinsecureprivatenetworkrequests" in out.lower():
        return out
    m = re.search(r"--disable-features=([^\s]+)", out)
    if m:
        feats = m.group(1)
        merged = f"{feats},{_EXTRA_PNA_DISABLE_FEATURES}"
        out = re.sub(
            r"--disable-features=[^\s]+",
            f"--disable-features={merged}",
            out,
            count=1,
        )
    else:
        out = f"{out} {_WEBVIEW2_LOOPBACK_ARGS}".strip()
    return out


def _install_pywebview_loopback_browser_args_patch() -> None:
    """Append loopback/PNA flags to pywebview's WebView2 ``CreationProperties`` (Windows)."""
    if sys.platform != "win32":
        return
    try:
        from webview.platforms import edgechromium as _ec
    except Exception:
        return
    if getattr(_ec.EdgeChrome, "_r5_loopback_args_patch", False):
        return

    _orig_init = _ec.EdgeChrome.__init__

    def _init_with_loopback(self, form, window, cache_dir):
        _orig_init(self, form, window, cache_dir)
        props = self.webview.CreationProperties
        if props is not None:
            props.AdditionalBrowserArguments = _append_loopback_flags_to_browser_args(
                props.AdditionalBrowserArguments or ""
            )

    _ec.EdgeChrome.__init__ = _init_with_loopback  # type: ignore[method-assign]
    _ec.EdgeChrome._r5_loopback_args_patch = True


def _webview2_container_is_loopback_exempt() -> bool:
    """Return True if the WebView2 AppContainer is already in the loopback exemption list."""
    try:
        creation = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            ["CheckNetIsolation", "LoopbackExempt", "-s"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creation,
        )
        return _WEBVIEW2_APPCONTAINER.lower() in result.stdout.lower()
    except Exception:
        return False


def _ensure_webview2_container_loopback_exempt() -> None:
    """Exempt the WebView2 renderer AppContainer from Windows loopback network isolation.

    The WebView2 renderer runs inside the AppContainer
    ``microsoft.win32webviewhost_cw5n1h2txyewy``.  Windows network isolation
    blocks that container from opening loopback TCP connections, so the renderer
    gets ERR_CONNECTION_REFUSED even when the Python health check succeeds from
    the (non-sandboxed) main process.

    Tries without elevation first; on access-denied prompts UAC via
    ``ShellExecuteExW("runas", ...)`` and waits up to 15 s for the user to act.
    """
    if sys.platform != "win32":
        return
    if _webview2_container_is_loopback_exempt():
        return

    creation = subprocess.CREATE_NO_WINDOW
    cmd_args = ["LoopbackExempt", "-a", f"-n={_WEBVIEW2_APPCONTAINER}"]

    # Try without elevation first (succeeds when already running as admin).
    try:
        result = subprocess.run(
            ["CheckNetIsolation"] + cmd_args,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creation,
        )
        if result.returncode == 0:
            return
    except FileNotFoundError:
        return  # CheckNetIsolation not present — nothing to do
    except Exception:
        pass

    # Need elevation: request UAC via ShellExecuteExW with the "runas" verb.
    try:
        import ctypes
        import ctypes.wintypes

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_HIDE = 0

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("fMask", ctypes.wintypes.DWORD),
                ("hwnd", ctypes.wintypes.HWND),
                ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p),
                ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p),
                ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p),
                ("hkeyClass", ctypes.wintypes.HKEY),
                ("dwHotKey", ctypes.wintypes.DWORD),
                ("hIconOrMonitor", ctypes.wintypes.HANDLE),
                ("hProcess", ctypes.wintypes.HANDLE),
            ]

        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = None
        sei.lpVerb = "runas"
        sei.lpFile = "CheckNetIsolation"
        sei.lpParameters = f'LoopbackExempt -a -n="{_WEBVIEW2_APPCONTAINER}"'
        sei.lpDirectory = None
        sei.nShow = SW_HIDE
        sei.hInstApp = None
        sei.hProcess = None

        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteExW.restype = ctypes.wintypes.BOOL
        shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
        ok = shell32.ShellExecuteExW(ctypes.byref(sei))

        if ok and sei.hProcess:
            kernel32 = ctypes.windll.kernel32
            kernel32.WaitForSingleObject(sei.hProcess, 15_000)
            kernel32.CloseHandle(sei.hProcess)
    except Exception as exc:
        print(f"Note: Could not apply WebView2 loopback exemption: {exc}", flush=True)


def _ensure_loopback_not_proxied() -> None:
    """Avoid corporate HTTP proxies hijacking ``127.0.0.1`` (urllib honors NO_PROXY)."""
    if "NO_PROXY" not in os.environ:
        os.environ["NO_PROXY"] = "127.0.0.1,localhost"


def _maybe_assign_ephemeral_ui_port() -> None:
    """If ``R5_SAVE_UI_PORT`` is ``0`` or ``auto``, bind an OS-assigned free port and sync URLs."""
    global API_PORT, API_URL, HEALTH_URL
    if _port_env_token() not in ("0", "auto"):
        return
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        API_PORT = int(s.getsockname()[1])
    os.environ["R5_SAVE_UI_PORT"] = str(API_PORT)
    API_URL = f"http://{API_HOST}:{API_PORT}/ui/"
    HEALTH_URL = f"http://{API_HOST}:{API_PORT}/api/health"


def _chromium_cli_loopback_flags() -> list[str]:
    """Flags for Edge/Chrome ``--app`` fallback so the UI can load http://127.0.0.1."""
    return [_WEBVIEW2_LOOPBACK_ARGS, "--allow-insecure-localhost"]


def _make_server() -> uvicorn.Server:
    # log_config=None disables uvicorn's default log formatter, which calls
    # sys.stdout.isatty() — crashing when stdout is None in a windowless EXE.
    # Force h11 + asyncio so the frozen bundle does not depend on optional httptools/uvloop.
    config = uvicorn.Config(
        "r5_save_tool.ui_api:app",
        host=_uvicorn_listen_host(),
        port=API_PORT,
        reload=False,
        log_config=None,
        access_log=False,
        loop="asyncio",
        http="h11",
    )
    return uvicorn.Server(config)


def _run_api(server: uvicorn.Server) -> None:
    """Run the FastAPI + uvicorn server in a thread."""
    # Proactor + asyncio in a non-main thread was unreliable on older Windows
    # Python builds; 3.14+ deprecates WindowsSelectorEventLoopPolicy (use default).
    if sys.platform == "win32" and sys.version_info < (3, 14):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    server.run()


def _is_frozen_bundle() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resolve_icon_path() -> str:
    if _is_frozen_bundle():
        p = Path(sys._MEIPASS) / "assets" / "icon.ico"
    else:
        p = Path(__file__).parent.parent / "assets" / "icon.ico"
    return str(p) if p.is_file() else ""


def _ensure_stdio_for_frozen_gui() -> None:
    """Attach writable streams when the PE subsystem is ``WINDOWS`` (``console=False``).

    Explorer double-click leaves ``sys.stdout`` / ``sys.stderr`` as ``None``; early
    ``print`` calls would raise and abort before the API or browser opens. A parent
    terminal (PowerShell) often inherits real handles, which is why ``& .\\dist\\…``
    can appear to work while a plain shortcut does not.

    This does **not** allocate a console: output is discarded (``nul`` / ``StringIO``)
    so the shipped EXE stays window-only for end users.
    """
    if not _is_frozen_bundle():
        return
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8", errors="replace")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8", errors="replace")
    except OSError:
        if sys.stdout is None:
            sys.stdout = io.StringIO()
        if sys.stderr is None:
            sys.stderr = io.StringIO()


def _uvicorn_listen_host() -> str:
    """Socket bind address for uvicorn (URLs in the UI still use ``API_HOST``)."""
    override = os.environ.get("R5_SAVE_UI_BIND", "").strip()
    if override:
        return override
    # Frozen Windows: binding only 127.0.0.1 can still yield WebView2 ERR_CONNECTION_REFUSED
    # on some setups; 0.0.0.0 accepts IPv4 loopback while clients use 127.0.0.1.
    if sys.platform == "win32" and _is_frozen_bundle():
        return "0.0.0.0"
    return API_HOST


def _spawn_internal_api_subprocess() -> subprocess.Popen:
    """Run the API in a separate interpreter (required for reliable WebView2 + asyncio on Windows)."""
    env = os.environ.copy()
    env[_INTERNAL_SERVER_ENV] = "1"
    creation = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        [sys.executable],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        close_fds=os.name != "nt",
        creationflags=creation,
    )


def _run_internal_server_main() -> None:
    """Entry for child: block on uvicorn (own process, main thread — stable asyncio)."""
    uvicorn.run(
        "r5_save_tool.ui_api:app",
        host=_uvicorn_listen_host(),
        port=API_PORT,
        reload=False,
        log_config=None,
        access_log=False,
        loop="asyncio",
        http="h11",
    )


def _stop_api_backend(
    server: uvicorn.Server | None,
    thread: threading.Thread | None,
    child: subprocess.Popen | None,
) -> None:
    """Stop either a subprocess API host or the in-process uvicorn thread."""
    if child is not None:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                child.kill()
        return
    if server is not None and thread is not None:
        server.should_exit = True
        thread.join(timeout=5)


def _health_opener() -> urllib.request.OpenerDirector:
    """Opener that never sends loopback health checks through an HTTP proxy."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _health_payload_is_windrose_api(data: object) -> bool:
    """True when JSON matches our /api/health contract (avoids false reuse on port 8765)."""
    if not isinstance(data, dict):
        return False
    if data.get("ok") is not True:
        return False
    status = data.get("status")
    if not isinstance(status, dict):
        return False
    return "manifest_found" in status


def _wait_for_api(timeout: float = STARTUP_TIMEOUT) -> bool:
    """Poll /api/health until our FastAPI app responds or the timeout expires."""
    deadline = time.monotonic() + timeout
    opener = _health_opener()
    while time.monotonic() < deadline:
        try:
            with opener.open(HEALTH_URL, timeout=1) as resp:
                if resp.status != 200:
                    continue
                raw = resp.read()
                try:
                    data = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    continue
                if _health_payload_is_windrose_api(data):
                    return True
        except Exception:
            pass
        time.sleep(0.15)
    return False


def _tcp_connect_ok(host: str, port: int, *, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ensure_loopback_accepts_before_ui(*, attempts: int = 40, delay_s: float = 0.05) -> bool:
    """Wait until the TCP listener accepts (avoids racing the WebView after HTTP health)."""
    for _ in range(attempts):
        if _tcp_connect_ok(API_HOST, API_PORT, timeout=0.35):
            return True
        time.sleep(delay_s)
    return False


def _port_in_use(host: str, port: int) -> bool:
    """Return True when a TCP listener is already bound to host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) == 0


def _iter_chromium_shell_candidates() -> list[Path]:
    """
    Return ordered unique paths to Chromium-based shells usable with ``--app=``.

    Edge/Chrome in app mode open a standalone window (not your default browser
    profile) so we can wait on the process and tear down the API when it exits.
    """
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen and p.is_file():
            seen.add(rp)
            candidates.append(p)

    if sys.platform == "win32":
        for name in ("msedge", "chrome"):
            w = shutil.which(name)
            if w:
                add(Path(w))
        for env_key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env_key)
            if not base:
                continue
            b = Path(base)
            add(b / "Microsoft" / "Edge" / "Application" / "msedge.exe")
            add(b / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif sys.platform == "darwin":
        for rel in (
            "Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ):
            add(Path("/") / rel)
    else:
        for name in (
            "microsoft-edge-stable",
            "microsoft-edge",
            "google-chrome",
            "chromium",
            "chromium-browser",
            "chrome",
        ):
            w = shutil.which(name)
            if w:
                add(Path(w))
    return candidates


def _try_start_chromium_app_mode(url: str) -> tuple[subprocess.Popen | None, Path | None]:
    """
    Start the first available Chromium shell in ``--app`` mode with an isolated profile.

    Returns ``(process, profile_dir)`` or ``(None, None)`` if no shell could be started.
    """
    for exe in _iter_chromium_shell_candidates():
        try:
            profile = Path(tempfile.mkdtemp(prefix="windrose-ui-appmode-"))
        except OSError:
            return None, None
        cmd = [
            str(exe),
            f"--app={url}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            *_chromium_cli_loopback_flags(),
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=os.name != "nt",
            )
            return proc, profile
        except OSError:
            shutil.rmtree(profile, ignore_errors=True)
            continue
    return None, None


def _wait_until_browser_exits(proc: subprocess.Popen) -> None:
    """Block until *proc* exits or the user interrupts; terminate stray processes."""
    try:
        while proc.poll() is None:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def launch() -> None:
    """
    Start the API then open a desktop window.

    Tries pywebview first (native window using the platform default — on
    Windows this is WebView2 / Edge Chromium, not Qt).
    If pywebview or its native backend is unavailable, falls back to Microsoft
    Edge or Google Chrome in ``--app`` mode (dedicated window, isolated profile)
    so closing that window ends the wait and allows API teardown. If neither
    browser is available, falls back to the system default browser (then you
    must stop this process manually with Ctrl+C when it owns the API).

    The browser UI (``/ui``) and JSON API (``/api``) share one host:port — one
    uvicorn process serves both. Set ``R5_SAVE_UI_PORT`` to ``0`` or ``auto``
    to pick a free port when the default is busy.
    """
    started_local_api = False
    api_server: uvicorn.Server | None = None
    t: threading.Thread | None = None
    api_child: subprocess.Popen | None = None
    _maybe_assign_ephemeral_ui_port()
    if sys.platform == "win32":
        _ensure_webview2_can_reach_loopback()
        _ensure_webview2_container_loopback_exempt()
    _ensure_loopback_not_proxied()
    print(f"Starting Windrose Save Tool API on port {API_PORT}...", flush=True)
    print(f"   UI (browser): {API_URL}", flush=True)
    print(f"   Health check: {HEALTH_URL}", flush=True)

    # If another UI instance is already running, reuse it instead of failing.
    if _wait_for_api(timeout=0.8):
        print(f"Note: Reusing existing UI API on port {API_PORT}.", flush=True)
        ready = True
    else:
        # If something else owns the port, fail cleanly with guidance.
        if _port_in_use(API_HOST, API_PORT):
            print(
                f"Warning: Port {API_PORT} is already in use by another process.\n"
                "   Stop that process or set a different R5_SAVE_UI_PORT before launch.",
                flush=True,
            )
            sys.exit(1)

        # On frozen Windows builds run uvicorn in a child process so its
        # asyncio event loop is completely isolated from pywebview's WinForms
        # message pump (which takes over the main thread in _wv.start()).
        if _is_frozen_bundle() and sys.platform == "win32":
            api_child = _spawn_internal_api_subprocess()
        else:
            api_server = _make_server()
            t = threading.Thread(target=_run_api, args=(api_server,), daemon=True)
            t.start()
        started_local_api = True
        ready = _wait_for_api()

    if not ready:
        print(
            f"Warning: API did not respond in time. Check that port {API_PORT} is free.",
            flush=True,
        )
        _stop_api_backend(api_server, t, api_child)
        sys.exit(1)

    # Reuse path already proved /api/health from a peer; only wait on TCP for
    # our own freshly started listener (avoids racing the WebView vs bind).
    if started_local_api and not _ensure_loopback_accepts_before_ui():
        print(
            f"Warning: {API_HOST}:{API_PORT} is not accepting connections before opening the UI.\n"
            "   Try closing other copies of this tool or set R5_SAVE_UI_PORT to a free port.",
            flush=True,
        )
        _stop_api_backend(api_server, t, api_child)
        sys.exit(1)

    try:
        import webview as _wv

        _install_pywebview_loopback_browser_args_patch()

        # Frozen EXE: open about:blank first, then load the UI URL after the window is
        # shown. Some WebView2 builds refuse the first navigation to loopback even when
        # the server is up; load_url() after shown avoids that race/policy edge case.
        def _navigate_after_shown() -> None:
            import webview as wv_nav

            if wv_nav.windows:
                wv_nav.windows[0].load_url(API_URL)

        ui_debug = os.environ.get("R5_SAVE_UI_DEBUG", "").strip() in ("1", "true", "yes")

        if _is_frozen_bundle():
            _wv.create_window(
                WINDOW_TITLE,
                url="about:blank",
                width=WINDOW_W,
                height=WINDOW_H,
                resizable=True,
                min_size=(900, 600),
            )
            _wv.start(debug=ui_debug, func=_navigate_after_shown)
        else:
            _wv.create_window(
                WINDOW_TITLE,
                url=API_URL,
                width=WINDOW_W,
                height=WINDOW_H,
                resizable=True,
                min_size=(900, 600),
            )
            _wv.start(debug=ui_debug)
        # Native window closed.
        if started_local_api:
            _stop_api_backend(api_server, t, api_child)
        sys.exit(0)
    except Exception as exc:
        # pywebview unavailable or backend missing; fall back to Chromium app mode.
        import webbrowser

        print(
            f"Note: pywebview unavailable ({exc.__class__.__name__}: {exc!r}).\n"
            f"   URL: {API_URL}",
            flush=True,
        )
        proc: subprocess.Popen | None = None
        profile_dir: Path | None = None
        try:
            proc, profile_dir = _try_start_chromium_app_mode(API_URL)
            if proc is not None:
                if started_local_api:
                    print(
                        "   Using Edge/Chrome app window (not your default browser profile).\n"
                        "   Close that window when finished to stop the local API.",
                        flush=True,
                    )
                else:
                    print(
                        "   Using Edge/Chrome app window.\n"
                        "   Close it when finished (the API keeps running in the other instance).",
                        flush=True,
                    )
                _wait_until_browser_exits(proc)
            else:
                print(
                    "   Could not find Microsoft Edge or Google Chrome for a dedicated app window.\n"
                    "   Opening your default browser instead.\n"
                    "   If this process owns the API, press Ctrl+C here when you are done.",
                    flush=True,
                )
                webbrowser.open(API_URL)
                if not started_local_api:
                    return
                try:
                    if api_child is not None:
                        while api_child.poll() is None:
                            time.sleep(1)
                    elif t is not None:
                        while t.is_alive():
                            t.join(timeout=1)
                except KeyboardInterrupt:
                    print("\nStopped.", flush=True)
        finally:
            if started_local_api:
                _stop_api_backend(api_server, t, api_child)
            if profile_dir is not None:
                shutil.rmtree(profile_dir, ignore_errors=True)


def main() -> None:
    _ensure_stdio_for_frozen_gui()
    from multiprocessing import freeze_support

    freeze_support()
    if os.environ.get(_INTERNAL_SERVER_ENV) == "1":
        _run_internal_server_main()
        return
    launch()


if __name__ == "__main__":
    main()
