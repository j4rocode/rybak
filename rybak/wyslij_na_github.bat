@echo off
rem =====================================================================
rem  DLA AUTORA: wrzuca ten folder na GitHuba jako nowa wersja.
rem  Uzytkownicy tego nie potrzebuja - im wystarczy przycisk
rem  "Sprawdz aktualizacje" w okienku programu.
rem
rem  PRZED URUCHOMIENIEM podnies numer wersji w rybak\__init__.py
rem
rem  Uwaga dla przyszlego mnie: w tym pliku nie ma blokow if ^( ... ^),
rem  tylko skoki przez goto. Powod jest prozaiczny: nawias zamykajacy w
rem  tresci komunikatu - chocby w slowie "przegladarke^)" - konczy blok w
rem  polowie, cmd wywala sie na skladni i okno gasnie bez slowa.
rem =====================================================================
setlocal
cd /d "%~dp0"
title Rybak - wysylka nowej wersji na GitHuba

set REPO=https://github.com/j4rocode/rybak.git

echo.
echo  === WYSYLKA NOWEJ WERSJI NA GITHUBA ===
echo.

rem --- czy na pewno stoimy w folderze programu
if not exist "rybak.py" goto zly_folder
if not exist "rybak\__init__.py" goto zly_folder

rem --- czy jest git
git --version >nul 2>&1
if errorlevel 1 goto brak_gita

rem --- numer wersji z kodu, do opisu zmiany
set WERSJA=nowa wersja
set POMOCNIK=%TEMP%\rybak_wersja.txt
if exist "%POMOCNIK%" del "%POMOCNIK%" >nul 2>&1
python -c "import re,io;print(re.search('__version__ = .(.*).',io.open('rybak/__init__.py',encoding='utf-8').read()).group(1))" > "%POMOCNIK%" 2>nul
if errorlevel 1 py -c "import re,io;print(re.search('__version__ = .(.*).',io.open('rybak/__init__.py',encoding='utf-8').read()).group(1))" > "%POMOCNIK%" 2>nul
if exist "%POMOCNIK%" set /p WERSJA=<"%POMOCNIK%"
if exist "%POMOCNIK%" del "%POMOCNIK%" >nul 2>&1

echo  Wersja: %WERSJA%
echo  Repozytorium: %REPO%
echo.

if exist ".git" goto juz_jest_repo
echo  Pierwszy raz - zakladam repozytorium w tym folderze...
git init
git branch -M main
git remote add origin %REPO%
goto wysylaj

:juz_jest_repo
git remote set-url origin %REPO% >nul 2>&1
if errorlevel 1 git remote add origin %REPO%

:wysylaj
echo.
echo  Zapisuje zmiany...
git add -A
git commit -m "Rybak %WERSJA%"
if errorlevel 1 echo  Nic sie nie zmienilo od ostatniego razu - wysylam to, co jest.
echo.
echo  Wysylam na GitHuba...
echo  Jesli to pierwszy raz, git otworzy teraz przegladarke i poprosi
echo  o zalogowanie na GitHuba. To jedyny taki raz.
echo.
git push -u origin main
if errorlevel 1 goto nie_poszlo

echo.
echo  === GOTOWE ===
echo  Wersja %WERSJA% jest na GitHubie. Na kazdym innym komputerze
echo  wystarczy teraz kliknac "Sprawdz aktualizacje".
goto koniec

:zly_folder
echo  Ten plik musi lezec w folderze programu, obok rybak.py
echo.
echo  Najczestsza przyczyna: uruchamiasz go PROSTO Z ZIP-a. Windows
echo  rozpakowuje wtedy jeden plik do folderu tymczasowego i skrypt nie
echo  widzi reszty programu.
echo.
echo  Rozpakuj caly ZIP na dysk - prawym przyciskiem na nim, potem
echo  "Wyodrebnij wszystkie" - i uruchom ten plik z rozpakowanego folderu.
goto koniec

:brak_gita
echo  Nie mam programu git.
echo.
echo  DROGA 1 - zainstaluj gita:
echo    https://git-scm.com/download/win
echo    Wszystkie opcje domyslne. Potem uruchom ten plik jeszcze raz.
echo.
echo  DROGA 2 - bez gita, przez przegladarke:
echo    1. Wejdz na https://github.com/j4rocode/rybak
echo    2. Kliknij "uploading an existing file"
echo    3. Przeciagnij tam zawartosc tego folderu (pliki i folder rybak^)
echo    4. Na dole kliknij "Commit changes"
goto koniec

:nie_poszlo
echo.
echo  Wysylka nie powiodla sie. Najczestsze powody:
echo.
echo    - git poprosil o zalogowanie, a okno logowania zostalo zamkniete.
echo      Uruchom ten plik jeszcze raz i zaloguj sie na GitHuba.
echo.
echo    - na GitHubie jest juz inna historia zmian. Wtedy wpisz w tym
echo      oknie:    git push -u origin main --force
echo      UWAGA: to nadpisze to, co jest teraz na GitHubie.
echo.
echo    - repozytorium nie istnieje albo nazwa sie nie zgadza. Sprawdz,
echo      czy dziala adres  https://github.com/j4rocode/rybak

:koniec
echo.
pause
