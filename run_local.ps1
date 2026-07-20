$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$envFile = Join-Path $root '.env'
if (-not (Test-Path -LiteralPath $python)) { throw '未找到 .venv，请先运行 .\install_local.ps1。' }
if (-not (Test-Path -LiteralPath $envFile)) { throw '未找到 .env，请复制 .env.example 并填写 FURCOLOR_ALLOWED_ROOTS。' }
Start-Process 'http://127.0.0.1:8899'
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8899 --env-file $envFile
