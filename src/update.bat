@echo off
echo Guncelleme yapiliyor, lutfen bekleyin...
timeout /t 3 /nobreak >nul
cd /d "C:\SorguSistemi\src"
powershell -command "Expand-Archive -Force 'C:\Users\ANIL\AppData\Local\Temp\tmpgjjx_hiv.zip' 'C:\SorguSistemi\src'"
del "C:\Users\ANIL\AppData\Local\Temp\tmpgjjx_hiv.zip" 2>nul
start "" "C:\SorguSistemi\src\SorguSistemi.exe"
del "%~f0"
