$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$BuildEnvironment = Join-Path $PSScriptRoot ".build-venv"
$BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $BuildPython)) {
    $Launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($Launcher) {
        & $Launcher.Source -3.13 -m venv $BuildEnvironment
        if ($LASTEXITCODE -ne 0) {
            & $Launcher.Source -3 -m venv $BuildEnvironment
        }
    }
    else {
        $Python = Get-Command python -ErrorAction Stop
        & $Python.Source -m venv $BuildEnvironment
    }
}

& $BuildPython -m pip install --disable-pip-version-check -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "安装打包依赖失败。" }

& $BuildPython -m PyInstaller --noconfirm --clean arcane_updater.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller构建失败。" }

$BundleDirectory = Join-Path $PSScriptRoot "dist\Warframe-Arcane-Return-Updater-Windows-x64"
$Executable = Join-Path $BundleDirectory "Warframe赋能收益表更新器.exe"
$Archive = Join-Path $PSScriptRoot "dist\Warframe-Arcane-Return-Updater-Windows-x64.zip"
if (-not (Test-Path -LiteralPath $Executable)) { throw "没有找到构建结果：$Executable" }

if (Test-Path -LiteralPath $Archive) {
    [System.IO.File]::Delete($Archive)
}
Compress-Archive -LiteralPath $BundleDirectory -DestinationPath $Archive -CompressionLevel Optimal
if (-not (Test-Path -LiteralPath $Archive)) { throw "没有找到 ZIP 构建结果：$Archive" }

Write-Host ""
Write-Host "文件夹版构建完成：$BundleDirectory" -ForegroundColor Green
Write-Host "ZIP 构建完成：$Archive" -ForegroundColor Green
