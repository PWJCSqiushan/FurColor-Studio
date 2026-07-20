[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$envFile = Join-Path $root '.env'
$model = Join-Path $root 'engine\models\face_detection_yunet_2023mar.onnx'
$errors = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]
if (-not (Test-Path -LiteralPath $python)) { $errors.Add('Python environment is missing. Run install_local.ps1.') }
if (-not (Test-Path -LiteralPath $envFile)) { $errors.Add('.env is missing. Run install_local.ps1 with -AllowedRoots.') }
if (-not (Test-Path -LiteralPath $model)) { $errors.Add('YuNet model is missing. Re-run install_local.ps1 with -DownloadFaceModel.') }
if (Test-Path -LiteralPath $envFile) {
  $line = Get-Content -LiteralPath $envFile -Encoding UTF8 | Where-Object { $_ -like 'FURCOLOR_ALLOWED_ROOTS=*' } | Select-Object -First 1
  if (-not $line) { $errors.Add('FURCOLOR_ALLOWED_ROOTS is missing from .env.') }
  else {
    $value = $line.Substring('FURCOLOR_ALLOWED_ROOTS='.Length)
    foreach ($item in $value.Split(';',[System.StringSplitOptions]::RemoveEmptyEntries)) {
      if (-not (Test-Path -LiteralPath $item.Trim() -PathType Container)) { $errors.Add("Allowed root does not exist: $($item.Trim())") }
    }
  }
}
if (Test-Path -LiteralPath $python) {
  & $python -c "import fastapi,uvicorn,jinja2,PIL,numpy,cv2,rawpy; print('Python imports: OK')"
  if ($LASTEXITCODE -ne 0) { $errors.Add('One or more Python dependencies cannot be imported.') }
}
if (Test-Path -LiteralPath $model) {
  $expected = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
  $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $model).Hash.ToLowerInvariant()
  if ($actual -ne $expected) { $warnings.Add('The face model is not the pinned official YuNet file. Continue only if you intentionally supplied a compatible model.') }
}
foreach ($warning in $warnings) { Write-Warning $warning }
if ($errors.Count -gt 0) {
  foreach ($message in $errors) { Write-Host "ERROR: $message" -ForegroundColor Red }
  exit 1
}
Write-Host 'Environment check: PASS' -ForegroundColor Green
exit 0
