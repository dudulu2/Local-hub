@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ==============================================
echo   LocalHub 本地媒体库
echo ==============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0server.py" --root "%~dp0"
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "%~dp0server.py" --root "%~dp0"
  goto :end
)

echo [错误] 没有检测到 Python 3。
echo 请安装 Python 3 后重新双击本文件。
echo 下载地址: https://www.python.org/downloads/windows/
echo.
pause

:end
endlocal
