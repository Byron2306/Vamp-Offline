from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from werkzeug.serving import make_server


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)).resolve()
    return Path(__file__).resolve().parents[1]


def _user_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "VAMP"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VAMP"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "vamp"


def _free_port(preferred: int = 5050) -> int:
    for port in [preferred, 5051, 5052, 5053, 5054, 5055, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return int(sock.getsockname()[1])
    return preferred


def main() -> int:
    app_root = _bundle_root()
    data_root = _user_data_dir()
    upload_root = data_root / "uploads"
    log_root = data_root / "logs"
    for path in (data_root, upload_root, log_root):
        path.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("VAMP_APP_ROOT", str(app_root))
    os.environ.setdefault("VAMP_RUNTIME_DIR", str(data_root))
    os.environ.setdefault("VAMP_DATA_DIR", str(data_root / "backend" / "data"))
    os.environ.setdefault("VAMP_UPLOAD_DIR", str(upload_root))
    os.environ.setdefault("VAMP_LOG_DIR", str(log_root))
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(data_root / "ms-playwright"))
    os.chdir(app_root)

    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))

    import run_web  # noqa: WPS433 - import after runtime env is intentional

    port = _free_port(int(os.getenv("VAMP_PORT", "5050")))
    url = f"http://127.0.0.1:{port}"
    try:
        run_web.sync_expectations_to_db()
    except Exception as exc:
        print(f"VAMP startup sync warning: {exc}")

    server = make_server("127.0.0.1", port, run_web.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"VAMP is running at {url}")
    time.sleep(0.8)
    webbrowser.open(url)

    try:
        while thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
