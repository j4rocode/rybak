@echo off
rem =====================================================================
rem  RYBAK - lowienie ryb w Metin2.  Kliknij dwa razy w ten plik.
rem  Windows zapyta o zgode administratora - kliknij TAK. Bez tego
rem  klawisze nie dojda do gry.
rem
rem  Uwaga dla przyszlego mnie: zadnych blokow if ^( ... ^) i zadnych
rem  nawiasow w tresci komunikatow. Nawias zamykajacy konczy blok w
rem  polowie, cmd wywala sie na skladni i okno gasnie bez slowa.
rem =====================================================================
net session >nul 2>&1
if errorlevel 1 goto podnies_uprawnienia
goto start

:podnies_uprawnienia
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:start
cd /d "%~dp0"
title Rybak

if not exist "rybak.py" goto zly_folder

set PY=
python --version >nul 2>&1
if not errorlevel 1 set PY=python
if defined PY goto mam_pythona
py --version >nul 2>&1
if not errorlevel 1 set PY=py
if defined PY goto mam_pythona
goto brak_pythona

:mam_pythona
%PY% -c "import numpy, cv2, mss" >nul 2>&1
if not errorlevel 1 goto uruchom
echo.
echo  Pierwsze uruchomienie - dogrywam biblioteki. Potrwa to kilka minut,
echo  tylko ten jeden raz.
echo.
call "%~dp0instaluj.bat"

:uruchom
%PY% rybak.py
if errorlevel 1 goto blad
exit /b 0

:zly_folder
echo.
echo  Nie widze pliku rybak.py obok tego skryptu.
echo.
echo  Najczestsza przyczyna: uruchamiasz PROSTO Z ZIP-a. Rozpakuj caly
echo  ZIP na dysk - prawym przyciskiem na nim, potem "Wyodrebnij
echo  wszystkie" - i uruchom Rybak.bat z rozpakowanego folderu.
echo.
pause
exit /b 1

:brak_pythona
echo.
echo  Nie znalazlem Pythona.
echo.
echo  1. Wejdz na https://www.python.org/downloads/
echo  2. Pobierz i zainstaluj. Na PIERWSZYM ekranie instalatora zaznacz
echo     "Add python.exe to PATH" - to wazne, bez tego nie znajde go
echo     nastepnym razem.
echo  3. Uruchom ten plik jeszcze raz.
echo.
pause
exit /b 1

:blad
echo.
echo  Cos poszlo nie tak - przeczytaj komunikat wyzej.
echo.
pause
exit /b 1
