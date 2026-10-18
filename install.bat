@echo off
chcp 65001 >nul 2>&1
setlocal

set "SRC=%~dp0."
set "DST=%USERPROFILE%\.workbuddy\skills\video-publish-prep"

echo.
echo   video-publish-prep  Installer
echo   ----------------------------------------
echo   Source : %SRC%
echo   Target : %DST%
echo.

if not exist "%SRC%\SKILL.md" (
    echo   [ERROR] SKILL.md not found. Please run this script inside the skill folder.
    echo.
    pause
    exit /b 1
)

echo   Copying files (skipping config.json / __pycache__) ...
robocopy "%SRC%" "%DST%" /E /XD __pycache__ .video-publish /XF config.json *.pyc *.pyo /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 (
    echo   [ERROR] Copy failed. Error code: %errorlevel%
    echo.
    pause
    exit /b 1
)

echo.
echo   [OK] Installed to:
echo        %DST%
echo.
echo   Next steps:
echo     1. Restart WorkBuddy / your agent client to load the skill.
echo     2. Optional: set your Agnes API Key (only needed for --ai-color)
echo            setx AGNES_API_KEY "sk-xxxx"
echo        or edit %DST%\config.json
echo.
echo   Quick try:
echo     python "%DST%\scripts\quick.py" --headline "Hello" --subheadline "World" --tone tech
echo.

endlocal
pause
