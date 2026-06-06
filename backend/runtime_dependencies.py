from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import requests


def _runtime_root() -> Path:
    configured = os.getenv("VAMP_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "VAMP"
    return Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "vamp"


def playwright_browsers_path() -> Path:
    path = Path(os.getenv("PLAYWRIGHT_BROWSERS_PATH") or _runtime_root() / "ms-playwright")
    path.mkdir(parents=True, exist_ok=True)
    return path


def playwright_status() -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {
            "available": False,
            "installed": False,
            "error": f"Playwright Python package unavailable: {exc}",
        }

    previous = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(playwright_browsers_path())
    try:
        with sync_playwright() as pw:
            executable = Path(pw.chromium.executable_path)
        return {
            "available": True,
            "installed": executable.exists(),
            "browser": "chromium",
            "executable": str(executable),
            "browsers_path": str(playwright_browsers_path()),
        }
    except Exception as exc:
        return {
            "available": True,
            "installed": False,
            "browser": "chromium",
            "browsers_path": str(playwright_browsers_path()),
            "error": str(exc),
        }
    finally:
        if previous is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = previous


def install_playwright_chromium(timeout: int = 1200) -> dict[str, Any]:
    try:
        from playwright._impl._driver import compute_driver_executable, get_driver_env
    except Exception as exc:
        return {"ok": False, "error": f"Playwright installer unavailable: {exc}"}

    browsers_path = playwright_browsers_path()
    env = get_driver_env()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
    driver_executable, driver_cli = compute_driver_executable()
    command = [driver_executable, driver_cli, "install", "chromium"]
    try:
        completed = subprocess.run(
            command,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "browsers_path": str(browsers_path)}

    status = playwright_status()
    return {
        "ok": completed.returncode == 0 and bool(status.get("installed")),
        "returncode": completed.returncode,
        "output": (completed.stdout or "")[-4000:],
        "status": status,
        "browsers_path": str(browsers_path),
    }


def ollama_status() -> dict[str, Any]:
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    try:
        response = requests.get(f"{host}/api/tags", timeout=2.5)
        response.raise_for_status()
        payload = response.json()
        models = [item.get("name") for item in payload.get("models", []) if item.get("name")]
        recommended_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        return {
            "available": True,
            "installed": True,
            "host": host,
            "models": models,
            "recommended_model": recommended_model,
            "recommended_model_installed": recommended_model in models,
        }
    except Exception as exc:
        return {
            "available": False,
            "installed": False,
            "host": host,
            "recommended_model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            "install_url": "https://ollama.com/download",
            "commands": ["ollama pull llama3.2:3b", "ollama serve"],
            "error": str(exc),
        }


def dependency_status() -> dict[str, Any]:
    return {
        "playwright": playwright_status(),
        "ollama": ollama_status(),
    }
