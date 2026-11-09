@echo off
setlocal
pushd "%~dp0" || exit /b 1

set "STUPID_PRINT_TK=import sys, tkinter; tkinter.Tcl(); sys.exit(sys.version_info < (3, 10))"
set "STUPID_PRINT_VENV=.venv"
set "STUPID_PRINT_REFRESH="
if not exist ".venv" goto create
".venv\Scripts\python.exe" -c "%STUPID_PRINT_TK%" >nul 2>&1 && goto check
set "STUPID_PRINT_VENV=.venv-tk"
".venv-tk\Scripts\python.exe" -c "%STUPID_PRINT_TK%" >nul 2>&1 && goto check

:create
set "STUPID_PRINT_REFRESH=1"
".runtime\python.exe" -c "%STUPID_PRINT_TK%" >nul 2>&1 && goto use_runtime
py -3 -c "%STUPID_PRINT_TK%" >nul 2>&1 && goto use_py
python -c "%STUPID_PRINT_TK%" >nul 2>&1 && goto use_python

echo Installing a Stupid Print Python runtime with Tcl/Tk.
set "STUPID_PRINT_MANAGER=pymanager.exe"
where pymanager.exe >nul 2>&1 && goto install_runtime
set "STUPID_PRINT_MANAGER=%LOCALAPPDATA%\Microsoft\WindowsApps\pymanager.exe"
if exist "%STUPID_PRINT_MANAGER%" goto install_runtime
where winget.exe >nul 2>&1 || goto missing_tk
winget.exe install -e --id 9NQ7512CXL7T --source msstore --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto missing_tk

:install_runtime
"%STUPID_PRINT_MANAGER%" install --target="%CD%\.runtime" 3.14
if errorlevel 1 goto missing_tk
".runtime\python.exe" -c "%STUPID_PRINT_TK%" >nul 2>&1 || goto missing_tk

:use_runtime
".runtime\python.exe" -m venv "%STUPID_PRINT_VENV%" || goto failed
goto check

:use_py
py -3 -m venv "%STUPID_PRINT_VENV%" || goto failed
goto check

:use_python
python -m venv "%STUPID_PRINT_VENV%" || goto failed

:check
set "STUPID_PRINT_PYTHON=%STUPID_PRINT_VENV%\Scripts\python.exe"
"%STUPID_PRINT_PYTHON%" -c "%STUPID_PRINT_TK%" || goto missing_tk
"%STUPID_PRINT_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%STUPID_PRINT_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 goto failed
)
if defined STUPID_PRINT_REFRESH goto install_deps
fc /b requirements.txt "%STUPID_PRINT_VENV%\stupid-print-requirements.txt" >nul 2>&1
if not errorlevel 1 goto launch

:install_deps
"%STUPID_PRINT_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
copy /y requirements.txt "%STUPID_PRINT_VENV%\stupid-print-requirements.txt" >nul

:launch
"%STUPID_PRINT_PYTHON%" -m stupid_print
if errorlevel 1 goto failed
popd
exit /b 0

:missing_tk
echo Install Python 3.10 or later from python.org with the Tcl/Tk and IDLE option, then rerun this launcher.
:failed
echo.
echo Stupid Print could not start. Review the error above.
popd
pause
exit /b 1
