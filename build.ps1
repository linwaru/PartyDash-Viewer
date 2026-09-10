$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = if (Test-Path .venv/Scripts/python.exe) { '.venv/Scripts/python.exe' } else { 'python' }
$version = (& $python -c "from version import VERSION; print(VERSION)").Trim()
if (-not $version) { throw 'Versão não encontrada em version.py' }
$assetPath = (Resolve-Path -LiteralPath 'assets').Path
$iconPath = (Resolve-Path -LiteralPath 'assets/branding/party-dash.ico').Path
& $python -m PyInstaller --noconfirm --windowed --onedir --specpath build/pyinstaller --icon $iconPath --add-data "$assetPath;assets" --name PartyDashViewer studio.py
if ($LASTEXITCODE -ne 0) { throw 'Falha no empacotamento' }
Compress-Archive -Path dist/PartyDashViewer -DestinationPath "dist/PartyDashViewer-v$version-Windows-x64.zip" -Force
