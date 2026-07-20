[CmdletBinding()]
param(
  [string]$AllowedRoots = '',
  [string]$FaceModelPath = '',
  [string]$PythonPath = '',
  [switch]$InstallPython,
  [switch]$DownloadFaceModel,
  [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$venvPython = Join-Path $root '.venv\Scripts\python.exe'

function New-FurColorVenv {
  if (Test-Path -LiteralPath $venvPython) { return }
  if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "PythonPath does not exist: $PythonPath" }
    $compatible = $false
    try {
      & $PythonPath -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)" 2>$null
      $compatible = ($LASTEXITCODE -eq 0)
    } catch { $compatible = $false }
    if (-not $compatible) { throw 'PythonPath must point to Python 3.11 or 3.12.' }
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'PythonPath could not create the virtual environment.' }
    return
  }
  $created = $false
  $python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in @('3.12','3.11')) {
      $compatible = $false
      try {
        & py "-$version" -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)" 2>$null
        $compatible = ($LASTEXITCODE -eq 0)
      } catch { $compatible = $false }
      if ($compatible) {
        & py "-$version" -m venv .venv
        if ($LASTEXITCODE -eq 0) { $created = $true; break }
      }
    }
  }
  if (-not $created -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $compatible = $false
    try {
      & python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)" 2>$null
      $compatible = ($LASTEXITCODE -eq 0)
    } catch { $compatible = $false }
    if ($compatible) { & python -m venv .venv; $created = ($LASTEXITCODE -eq 0) }
  }
  if (-not $created -and (Test-Path -LiteralPath $python312)) {
    & $python312 -m venv .venv
    $created = ($LASTEXITCODE -eq 0)
  }
  if (-not $created) {
    $shouldInstall = $InstallPython
    if (-not $shouldInstall) {
      $answer = Read-Host 'Python 3.11/3.12 was not found. Install Python 3.12 with winget now? [Y/n]'
      $shouldInstall = ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^[Yy]')
    }
    if (-not $shouldInstall) { throw 'Python 3.11 or 3.12 is required. Re-run with -InstallPython or install Python 3.12 manually.' }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'winget is unavailable. Install Python 3.12 from https://www.python.org/downloads/ and run this script again.' }
    Write-Host 'Installing Python 3.12 for the current Windows user...'
    & winget install --id Python.Python.3.12 -e --version 3.12.10 --source winget --scope user --force --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw 'winget could not install Python 3.12.' }
    if (-not (Test-Path -LiteralPath $python312)) { throw "Python 3.12 was installed but not found at: $python312. Open a new PowerShell window and run this script again." }
    & $python312 -m venv .venv
    $created = ($LASTEXITCODE -eq 0)
  }
  if (-not $created) { throw 'Could not create the Python virtual environment.' }
}

function Write-FurColorEnv([string]$rootsValue) {
  $resolved = @()
  foreach ($item in $rootsValue.Split(';',[System.StringSplitOptions]::RemoveEmptyEntries)) {
    $candidate = $item.Trim()
    if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { throw "Allowed photo root does not exist: $candidate" }
    $resolved += (Resolve-Path -LiteralPath $candidate).Path
  }
  if ($resolved.Count -eq 0) { throw 'At least one existing photo root is required.' }
  $content = @(
    'FURCOLOR_MODE=local',
    'FURCOLOR_HOST=127.0.0.1',
    'FURCOLOR_PORT=8899',
    'FURCOLOR_DATA_DIR=./runtime',
    'FURCOLOR_ENGINE_ROOT=./engine',
    ('FURCOLOR_ALLOWED_ROOTS=' + ($resolved -join ';'))
  ) -join [Environment]::NewLine
  $utf8 = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText((Join-Path $root '.env'),$content+[Environment]::NewLine,$utf8)
}

function Install-FaceModel {
  $models = Join-Path $root 'engine\models'
  $target = Join-Path $models 'face_detection_yunet_2023mar.onnx'
  New-Item -ItemType Directory -Force -Path $models | Out-Null
  if ($FaceModelPath) {
    if (-not (Test-Path -LiteralPath $FaceModelPath -PathType Leaf)) { throw "Face model not found: $FaceModelPath" }
    Copy-Item -LiteralPath $FaceModelPath -Destination $target -Force
    return
  }
  $shouldDownload = $DownloadFaceModel
  if (-not $shouldDownload -and -not (Test-Path -LiteralPath $target)) {
    $answer = Read-Host 'Download the official OpenCV YuNet model (MIT license)? [Y/n]'
    $shouldDownload = ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^[Yy]')
  }
  if (-not $shouldDownload) { return }
  $url = 'https://github.com/opencv/opencv_zoo/raw/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'
  $expected = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
  $temporary = Join-Path $env:TEMP ('furcolor-yunet-' + [guid]::NewGuid().ToString('N') + '.onnx')
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $temporary
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $temporary).Hash.ToLowerInvariant()
    if ($actual -ne $expected) { throw "YuNet SHA-256 mismatch. Expected $expected, received $actual" }
    Move-Item -LiteralPath $temporary -Destination $target -Force
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}

Write-Host '[1/5] Preparing Python 3.11/3.12 environment...'
New-FurColorVenv
Write-Host '[2/5] Installing pinned dependencies...'
& $venvPython -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host '[3/5] Configuring allowed photo roots...'
if ($AllowedRoots) { Write-FurColorEnv $AllowedRoots }
elseif (-not (Test-Path -LiteralPath '.env')) {
  $AllowedRoots = Read-Host 'Enter allowed photo roots, separated by semicolons (example: D:\Photos;E:\Events)'
  Write-FurColorEnv $AllowedRoots
}
Write-Host '[4/5] Preparing the face detector...'
Install-FaceModel
Write-Host '[5/5] Running environment checks...'
& (Join-Path $root 'doctor.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Environment check failed. Read the messages above.' }
Write-Host ''
Write-Host 'FurColor Studio is ready.' -ForegroundColor Green
Write-Host 'Start later with: .\run_local.ps1'
if ($Launch) { & (Join-Path $root 'run_local.ps1') }
