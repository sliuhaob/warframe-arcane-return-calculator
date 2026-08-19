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

$Executable = Join-Path $PSScriptRoot "dist\Warframe赋能收益表更新器.exe"
if (-not (Test-Path -LiteralPath $Executable)) { throw "没有找到构建结果：$Executable" }

Write-Host ""
Write-Host "构建完成：$Executable" -ForegroundColor Green
