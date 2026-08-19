@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
title Warframe Arcane Return Calculator

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "WORK_DIR=%TEMP%\warframe_arcane_return"
set "OUTPUT_DIR=%SCRIPT_DIR%outputs\daily_arcane_return"
set "OUTPUT_FILE=%OUTPUT_DIR%\赋能收益表_最新.xlsx"

if exist "%OUTPUT_DIR%\~$*.xlsx" goto workbook_open

if exist "%VENV_PYTHON%" goto dependencies
set "BASE_PYTHON="
for /f "delims=" %%P in ('where py 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%~fP -3"
if defined BASE_PYTHON goto create_venv
for /f "delims=" %%P in ('where python 2^>nul') do if not defined BASE_PYTHON set "BASE_PYTHON=%%~fP"
if not defined BASE_PYTHON goto python_missing

:create_venv
echo Creating a local Python environment...
%BASE_PYTHON% -m venv "%VENV_DIR%"
if errorlevel 1 goto venv_failed

:dependencies
"%VENV_PYTHON%" -c "import openpyxl" >nul 2>&1
if not errorlevel 1 goto run_update
echo Installing the Excel dependency...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -r "%SCRIPT_DIR%requirements.txt"
if errorlevel 1 goto dependency_failed

:run_update
if not exist "%WORK_DIR%" mkdir "%WORK_DIR%"
if errorlevel 1 goto workdir_failed
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"
if errorlevel 1 goto workdir_failed

set "PRICE_CSV=%WORK_DIR%\arcane_prices.csv"
set "SUMMARY_CSV=%WORK_DIR%\pack_summary.csv"
set "DATA_JSON=%WORK_DIR%\arcane_data.json"

pushd "%SCRIPT_DIR%"
if defined ARCANE_DAILY_REUSE_DATA if exist "%DATA_JSON%" goto build_workbook
echo Fetching Warframe Market 48-hour Arcane data...
echo This normally takes about 2-4 minutes.
"%VENV_PYTHON%" "warframe_arcane_prices.py" --output "%PRICE_CSV%" --summary-output "%SUMMARY_CSV%" --json "%DATA_JSON%" --preview 0
set "FETCH_EXIT=!ERRORLEVEL!"
if not "!FETCH_EXIT!"=="0" (
  popd
  goto fetch_failed
)

:build_workbook
echo Building and checking the Excel workbook...
"%VENV_PYTHON%" "build_arcane_workbook.py" "%DATA_JSON%" "%OUTPUT_FILE%"
set "BUILD_EXIT=!ERRORLEVEL!"
popd
if not "!BUILD_EXIT!"=="0" goto build_failed

echo.
echo Update completed successfully:
echo %OUTPUT_FILE%
if defined ARCANE_DAILY_NO_OPEN exit /b 0
start "" "%OUTPUT_FILE%"
exit /b 0

:workbook_open
echo The output workbook is open in Excel. Close it and run this updater again.
goto pause_error

:python_missing
echo Python 3.10 or newer was not found. Install Python from https://python.org/
goto pause_error

:venv_failed
echo Failed to create the local Python environment.
goto pause_error

:dependency_failed
echo Failed to install Python dependencies.
goto pause_error

:workdir_failed
echo Failed to create the working or output directory.
goto pause_error

:fetch_failed
echo Data update failed with exit code !FETCH_EXIT!.
goto pause_error

:build_failed
echo Workbook generation failed with exit code !BUILD_EXIT!.
goto pause_error

:pause_error
echo.
if not defined ARCANE_DAILY_NO_PAUSE pause
exit /b 1
