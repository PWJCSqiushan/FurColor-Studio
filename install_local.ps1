param([string]$FaceModelPath = '')
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $root
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
  $created = $false
  foreach ($version in @('3.12','3.11')) {
    try { & py "-$version" -m venv .venv; if ($LASTEXITCODE -eq 0) { $created=$true; break } } catch { }
  }
  if (-not $created) { throw '需要 Python 3.11 或 3.12。请安装后重新运行本脚本。' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
if ($FaceModelPath) {
  if (-not (Test-Path -LiteralPath $FaceModelPath -PathType Leaf)) { throw "人脸模型不存在：$FaceModelPath" }
  New-Item -ItemType Directory -Force -Path '.\engine\models' | Out-Null
  Copy-Item -LiteralPath $FaceModelPath -Destination '.\engine\models\face_detection_yunet_2023mar.onnx' -Force
}
Write-Host '安装完成。运行 .\run_local.ps1 启动本地工作站。'
if (-not (Test-Path -LiteralPath '.\engine\models\face_detection_yunet_2023mar.onnx')) {
  Write-Warning '尚未安装 YuNet ONNX 模型；选片可用，但分析前必须按 engine\README.md 准备模型并核对许可证。'
}
