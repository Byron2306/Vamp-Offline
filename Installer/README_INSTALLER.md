# VAMP Installer Packaging

This packages the root VAMP web app (`run_web.py`) as a local desktop app. The installed shortcut launches a local server, opens the browser, and stores user data under the user's profile instead of inside the install directory.

## Windows Website Installer

1. Build on Windows.
2. Install Inno Setup 6.
3. From PowerShell:

```powershell
.\scripts\build_windows_installer.ps1
```

Output:

```text
dist\installer\VAMP_Setup_0.1.0.exe
```

Upload that `.exe` to the website as the Windows download.

## Icon

The installer and final shortcut use:

```text
frontend/offline_app/icon128.png
Installer/assets/vamp.ico
```

## Runtime Data

Installed VAMP stores evidence, progress, uploads, Outlook session state, and logs in:

```text
%LOCALAPPDATA%\VAMP
```

That keeps updates/install repairs from overwriting a user's evidence trail.

## Thin Runtime Dependencies

The Windows installer is intentionally thin. It ships VAMP, the Python app, and the Playwright Python driver, but it does **not** ship the Chromium browser binary or Ollama models.

After first launch, open **Runtime Dependencies** in the VAMP enrolment screen:

- **Check Dependencies** shows whether Playwright Chromium is already installed for this user and whether Ollama is running.
- **Install Browser Automation** downloads Playwright Chromium into `%LOCALAPPDATA%\VAMP\ms-playwright`. This enables Outlook and eFundi automation.
- **Ollama** remains optional. If the user wants local LLM scoring instead of a remote provider, install Ollama from `https://ollama.com/download`, then run `ollama pull llama3.2:3b`.

This keeps the setup file much smaller and avoids bundling heavyweight browser/runtime assets that can be repaired or updated per user.

## Notes

- Code-signing is strongly recommended before public download, otherwise Windows SmartScreen will warn users.
- Outlook/eFundi automation requires Playwright Chromium. VAMP installs it on demand into the user's runtime data folder.
- Keep sensitive local data out of the installer. Do not bundle `backend/data/outlook`, `backend/data/progress`, `cache/voice`, `.venv`, `logs`, or real evidence folders.
