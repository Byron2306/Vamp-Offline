param(
  [string]$InnoSetupCompiler = "iscc"
)

$ErrorActionPreference = "Stop"
$Repo = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Repo

if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller

& .\.venv\Scripts\pyinstaller.exe --clean --noconfirm packaging\vamp_pyinstaller.spec

if (-not (Get-Command $InnoSetupCompiler -ErrorAction SilentlyContinue)) {
  throw "Inno Setup compiler '$InnoSetupCompiler' was not found. Install Inno Setup 6 and ensure ISCC.exe is on PATH, or pass -InnoSetupCompiler 'C:\Path\To\ISCC.exe'."
}

& $InnoSetupCompiler packaging\VAMP.iss
Write-Host "Installer built in dist\installer"
