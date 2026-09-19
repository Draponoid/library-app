$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Установите Python 3.11 или новее и добавьте его в PATH.' }
}
& '.venv/Scripts/python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
if (-not (Test-Path '.env')) {
    & '.venv/Scripts/python.exe' setup_local.py
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать конфигурацию.' }
}
& '.venv/Scripts/python.exe' app.py run
