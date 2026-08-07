@echo off
:: Creates a JARVIS shortcut on the Desktop
set SCRIPT=%~dp0start_jarvis.bat
set SHORTCUT=%USERPROFILE%\Desktop\JARVIS.lnk

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [System.Environment]::GetFolderPath('Desktop'); $s = $ws.CreateShortcut($desktop + '\JARVIS.lnk'); $s.TargetPath = '%SCRIPT%'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = 'shell32.dll,14'; $s.Description = 'Start JARVIS'; $s.Save()"

echo  Shortcut created on Desktop: JARVIS.lnk
echo  Double-click it anytime to start JARVIS.
pause
