# MailHubLauncher.exe 一键构建脚本
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "[1/2] 正在同步与准备启动器视觉素材及程序图标..." -ForegroundColor Magenta
python "launcher_app/prepare_assets.py"

Write-Host "[2/2] 正在使用 PyInstaller 打包 MailHubLauncher.exe..." -ForegroundColor Magenta
python -m PyInstaller --noconfirm --distpath . --workpath "launcher_app/build" "launcher_app/MailHubLauncher.spec"

$ExePath = Join-Path $ProjectRoot "MailHubLauncher.exe"
if (-not (Test-Path $ExePath)) {
    throw "打包失败：未生成 $ExePath"
}

$SizeMB = [math]::Round((Get-Item $ExePath).Length / 1MB, 2)
Write-Host "打包完成：$ExePath ($SizeMB MB)" -ForegroundColor Green
