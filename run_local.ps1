$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$envFile = Join-Path $root '.env'
& (Join-Path $root 'doctor.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed.' }
$portLine = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -like 'FURCOLOR_PORT=*' } | Select-Object -First 1
$port = if ($portLine) { $portLine.Substring('FURCOLOR_PORT='.Length).Trim() } else { '8899' }
$url = "http://127.0.0.1:$port"
Write-Host "Starting FurColor Studio at $url"
Start-Process $url
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $port --env-file $envFile
