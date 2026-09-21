@echo off
rem Dogrywa biblioteki, ktorych Rybak potrzebuje. Normalnie wola go
rem Rybak.bat sam - uruchom recznie tylko wtedy, gdy cos nie poszlo.
rem
rem Zadnych blokow if ^( ... ^) - patrz komentarz w Rybak.bat.
setlocal
cd /d "%~dp0"
title Rybak - instalacja bibliotek

echo.
echo  === INSTALACJA BIBLIOTEK ===
echo.

set PY=
python --version >nul 2>&1
if not errorlevel 1 set PY=python
if defined PY goto mam
py --version >nul 2>&1
if not errorlevel 1 set PY=py
if defined PY goto mam
goto brak_pythona

:mam
%PY% --version
echo.
echo  Pobieram numpy, opencv-python i mss...
echo.
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto nie_poszlo

echo.
echo  Sprawdzam, czy wszystko sie wczytuje...
%PY% -c "import numpy, cv2, mss; print('   numpy ', numpy.__version__); print('   opencv', cv2.__version__); print('   mss    OK')"
if errorlevel 1 goto nie_wczytuje

echo.
echo  === GOTOWE === Mozesz zamknac to okno i uruchomic Rybak.bat
echo.
pause
exit /b 0

:brak_pythona
echo  Nie znalazlem Pythona. Pobierz go z https://www.python.org/downloads/
echo  i przy instalacji zaznacz "Add python.exe to PATH".
echo.
pause
exit /b 1

:nie_poszlo
echo.
echo  Instalacja nie powiodla sie. Najczestsze powody:
echo    - brak internetu albo blokada firmowego proxy lub VPN
echo    - Python ze Sklepu Windows; wez wersje z python.org
echo.
pause
exit /b 1

:nie_wczytuje
echo.
echo  Biblioteki sie zainstalowaly, ale nie daja sie wczytac.
echo  Pokaz komunikat powyzej osobie, ktora dala Ci ten program.
echo.
pause
exit /b 1
