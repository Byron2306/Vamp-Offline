# Build with:
#   pyinstaller --clean --noconfirm packaging/vamp_pyinstaller.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd()


def data(src: str, dest: str = "."):
    return (str(ROOT / src), dest)


datas = [
    data("index.html"),
    data("app.js"),
    data("vamp.css"),
    data("vampire.mp4"),
    data("vamp.wav"),
    data("NWU-holding-shape-digital-white.png"),
    data("Cinzel-VariableFont_wght.ttf"),
    data("CloisterBlackLight-axjg.ttf"),
    data("frontend/offline_app/icon128.png", "frontend/offline_app"),
    data("backend/knowledge", "backend/knowledge"),
    data("evidence_taxonomy.json"),
]
# Keep Playwright's Python package data and driver, but do not bundle Chromium.
# Chromium is downloaded on first run into the user's VAMP runtime directory.
datas += collect_data_files("playwright")


a = Analysis(
    ["packaging/desktop_launcher.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "flask",
        "flask_cors",
        "werkzeug.serving",
        "openpyxl",
        "pandas",
        "PyPDF2",
        "pdfminer",
        "pdfplumber",
        "docx",
        "pptx",
        "playwright.sync_api",
    ] + collect_submodules("playwright"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["node_modules", "tests", ".venv", ".git"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VAMP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="packaging/assets/vamp.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VAMP",
)
