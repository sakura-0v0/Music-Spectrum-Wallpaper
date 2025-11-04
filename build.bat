
:: ================= 配置区 =================
set "icospath=E:\sound_line\"
set "appname=小娥频谱显示"
set "PRO_SPEC=run.spec"
set "SIGN=E:\sound_line\"
set "BAG_ROOT=E:\app_bag"


echo =========打包项目==========
call activate sound_line3.7
call cd /d E:\sound_line
call pyinstaller --noconfirm --clean %PRO_SPEC%
echo =========打包项目完成！==========

timeout /t 2 /nobreak >nul
echo =========签名程序==========
set "text=123456"
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [Windows.Forms.Clipboard]::SetText(\"%text%\")"
echo 文本已复制到剪贴板！

call cd /d "E:\sound_line\dist\app"
start "" /B cscript //nologo "E:\oem_icos\paste_at_3s.vbs"
call E:\app_bag\dist\signcode.exe -spc "%SIGN%证书.cer" -v "%SIGN%证书.pvk" -n "%appname%" -t "http://tsa.starfieldtech.com" -p "%text%" %appname%.exe

echo =========签名程序完成！==========


timeout /t 2 /nobreak >nul

:: =============== spec文件同步 ===============
setlocal enabledelayedexpansion
echo 正在同步.spec文件...
set "SOURCE_SPEC=%icospath%bag.spec"
set "TARGET_SPEC=%BAG_ROOT%\bag.spec"

xcopy /Y /F /R "%SOURCE_SPEC%" "%BAG_ROOT%\" >nul
if %errorlevel% neq 0 (
    echo [错误] spec文件复制失败！
    pause
    exit /b 1
)

echo spec文件同步完成
echo =========制作安装包==========
call activate app_bag
call cd /d E:\app_bag
call pyinstaller --noconfirm --clean "bag.spec"
echo =========制作安装包完成！==========
timeout /t 2 /nobreak >nul
echo =========签名安装包======123456
====
set "text=123456"
powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [Windows.Forms.Clipboard]::SetText(\"%text%\")"
echo 文本已复制到剪贴板！

call cd /d "E:\app_bag\dist"
start "" /B cscript //nologo "E:\oem_icos\paste_at_3s.vbs"
call signcode.exe -spc "%SIGN%证书.cer" -v "%SIGN%证书.pvk" -n "%appname%" -t http://tsa.starfieldtech.com "%appname%安装包.exe"

echo =========签名安装包完成！==========
pause
cmd /k
