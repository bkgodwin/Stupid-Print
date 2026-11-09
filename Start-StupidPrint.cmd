@echo off
setlocal
pushd "%~dp0" || exit /b 1

if exist ".venv\Scripts\python.exe" goto check
where py >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto check

:use_python
python -m venv .venv
if errorlevel 1 goto failed

:check
set "STUPID_PRINT_PYTHON=.venv\Scripts\python.exe"
"%STUPID_PRINT_PYTHON%" -c "import sys, tkinter; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Stupid Print requires Python 3.10 or newer with Tcl/Tk.
    goto failed
)
"%STUPID_PRINT_PYTHON%" -m pip --version >nul 2>&1
if errorlevel 1 (
    "%STUPID_PRINT_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 goto failed
)
fc /b requirements.txt ".venv\stupid-print-requirements.txt" >nul 2>&1
if not errorlevel 1 goto launch
"%STUPID_PRINT_PYTHON%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
copy /y requirements.txt ".venv\stupid-print-requirements.txt" >nul

:launch
"%STUPID_PRINT_PYTHON%" -m stupid_print
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo.
echo Stupid Print could not start. Review the error above.
popd
pause
exit /b 1
