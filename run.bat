@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY=C:\Users\26852\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

echo [1/2] 解析账单并生成数据...
"%PY%" -m moneylens.build
if errorlevel 1 (
  echo 构建失败，请检查上面的报错。
  pause
  exit /b 1
)

echo [2/2] 打开仪表盘...
start "" "%~dp0web\index.html"
endlocal