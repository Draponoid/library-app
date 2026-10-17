$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python setup_local.py
if ($LASTEXITCODE -ne 0) { throw 'Initial setup failed.' }
& '.venv/Scripts/python.exe' app.py run
