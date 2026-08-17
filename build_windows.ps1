$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw '未找到 Python。开发者本地构建需要 Python 3.11+；普通用户直接下载 LocalHub.exe 即可。'
}

python -m pip install --upgrade pyinstaller pystray pillow
python tools/make_icon.py
python -m PyInstaller --noconfirm --clean LocalHub.spec

$hash = (Get-FileHash .\dist\LocalHub.exe -Algorithm SHA256).Hash.ToLower()
"LocalHub.exe  $hash" | Set-Content .\dist\SHA256.txt -Encoding utf8
Write-Host ''
Write-Host '构建完成：' -ForegroundColor Green
Write-Host "  $PSScriptRoot\dist\LocalHub.exe"
Write-Host "SHA256: $hash"
