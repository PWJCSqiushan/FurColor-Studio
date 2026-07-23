[CmdletBinding()]
param(
  [string]$ModelDirectory = '',
  [string]$PythonPath = '',
  [switch]$CpuOnly,
  [switch]$Launch
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
$venvPython = Join-Path $root '.venv-fursee\Scripts\python.exe'
$basePython = Join-Path $root '.venv\Scripts\python.exe'
$manifest = Join-Path $root 'engine\config\fursee_model_manifest.json'
$verifyScript = Join-Path $root 'engine\src\verify_fursee.py'
$envFile = Join-Path $root '.env'

function Resolve-CompatiblePython {
  if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "PythonPath does not exist: $PythonPath" }
    return (Resolve-Path -LiteralPath $PythonPath).Path
  }
  if (Test-Path -LiteralPath $basePython -PathType Leaf) { return $basePython }
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($version in @('3.12','3.11')) {
      & py "-$version" -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,12)" 2>$null
      if ($LASTEXITCODE -eq 0) { return "py|-$version" }
    }
  }
  throw 'Python 3.11/3.12 was not found. Run install_local.ps1 first or pass -PythonPath.'
}

function Set-EnvValue([string]$Name,[string]$Value) {
  $lines = @()
  if (Test-Path -LiteralPath $envFile) { $lines = @(Get-Content -LiteralPath $envFile -Encoding UTF8) }
  $replacement = "$Name=$Value"
  $updated = $false
  for ($index = 0; $index -lt $lines.Count; $index++) {
    if ($lines[$index] -like "$Name=*") { $lines[$index] = $replacement; $updated = $true }
  }
  if (-not $updated) { $lines += $replacement }
  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($envFile,($lines -join [Environment]::NewLine)+[Environment]::NewLine,$encoding)
}

if (-not $ModelDirectory) { $ModelDirectory = Read-Host 'Enter the local Fursee model package directory' }
if (-not (Test-Path -LiteralPath $ModelDirectory -PathType Container)) { throw "Model directory does not exist: $ModelDirectory" }
$resolvedModel = (Resolve-Path -LiteralPath $ModelDirectory).Path

Write-Host '[1/5] Creating the isolated Fursee environment...'
if (-not (Test-Path -LiteralPath $venvPython)) {
  $source = Resolve-CompatiblePython
  if ($source -like 'py|*') {
    $selector = $source.Substring(3)
    & py $selector -m venv .venv-fursee
  } else {
    & $source -m venv .venv-fursee
  }
  if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv-fursee.' }
}

Write-Host '[2/5] Installing PyTorch...'
if ($CpuOnly) {
  & $venvPython -m pip install --disable-pip-version-check torch==2.7.1 torchvision==0.22.1
} else {
  & $venvPython -m pip install --disable-pip-version-check torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu128
}
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed.' }

Write-Host '[3/5] Installing Fursee adapter dependencies...'
& $venvPython -m pip install --disable-pip-version-check -r requirements-fursee.txt
if ($LASTEXITCODE -ne 0) { throw 'Fursee dependency installation failed.' }

Write-Host '[4/5] Verifying local model sizes and SHA-256 hashes...'
& $venvPython $verifyScript --model-dir $resolvedModel --manifest $manifest --hash
if ($LASTEXITCODE -ne 0) { throw 'The Fursee model package did not match the pinned manifest.' }

Write-Host '[5/5] Saving local-only configuration...'
Set-EnvValue 'FURCOLOR_FURSEE_MODEL_DIR' $resolvedModel
Set-EnvValue 'FURCOLOR_FURSEE_PYTHON' $venvPython
Write-Host 'Fursee subject intelligence is ready. Model files were referenced in place and were not copied.' -ForegroundColor Green
if ($Launch) { & (Join-Path $root 'run_local.ps1') }