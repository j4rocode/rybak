@echo off
rem =====================================================================
rem  DLA AUTORA: wrzuca ten folder na GitHuba jako nowa wersja.
rem  Uzytkownicy tego nie potrzebuja - im wystarczy przycisk
rem  "Sprawdz aktualizacje" w okienku programu.
rem
rem  PRZED URUCHOMIENIEM podnies numer wersji w rybak\__init__.py
rem
rem  Dwie zasady, obie okupione debugowaniem:
rem  1. Zadnych blokow if ^( ... ^) - nawias zamykajacy w tresci
rem     komunikatu konczy blok w polowie i okno gasnie bez slowa.
rem  2. Zadnych plikow tymczasowych do przechwytywania wyniku - od tego
rem     jest  for /f  . Sciezka z "\r" potrafi wpasc do pliku jako
rem     prawdziwy znak powrotu karetki i rozwalic parsowanie.
rem =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Rybak - wysylka nowej wersji na GitHuba

set REPO=https://github.com/j4rocode/rybak.git

echo.
echo  === WYSYLKA NOWEJ WERSJI NA GITHUBA ===
echo.

if not exist "rybak.py" goto zly_folder
if not exist "rybak\__init__.py" goto zly_folder

git --version >nul 2>&1
if errorlevel 1 goto brak_gita

set WERSJA=nowa wersja
rem Numer wersji czytamy wprost z pliku - bez Pythona i bez cudzyslowow
rem w cudzyslowach. Linia wyglada tak:  __version__ = "2.10"
rem Delimitery "=" i spacja daja drugi token "2.10", a %%~v zdejmuje cudzyslowy.
for /f "tokens=2 delims== " %%v in ('findstr /b "__version__" rybak\__init__.py') do set WERSJA=%%~v

echo  Wersja: %WERSJA%
echo  Repozytorium: %REPO%

if exist ".git" goto juz_jest_repo
echo.
echo  Pierwszy raz - zakladam repozytorium w tym folderze...
git init
git branch -M main
git remote add origin %REPO%
goto wysylaj

:juz_jest_repo
git remote set-url origin %REPO% >nul 2>&1
if errorlevel 1 git remote add origin %REPO%

:wysylaj
rem Przerwany git zostawia blokade, przez ktora kazde kolejne "git add"
rem konczy sie bledem. Plik jest pusty i nic nie chroni, gdy zaden git
rem juz nie dziala - a tu zaden nie dziala, bo dopiero startujemy.
if exist ".git\index.lock" del ".git\index.lock" >nul 2>&1

echo.
echo  Zapisuje zmiany...
git add -A
if errorlevel 1 goto blad_zapisu
git commit -m "Rybak %WERSJA%"

echo.
echo  Sprawdzam, co jest na GitHubie...
git fetch origin
git rev-parse --verify origin/main >nul 2>&1
if errorlevel 1 goto wysylaj_teraz
git merge-base origin/main HEAD >nul 2>&1
if errorlevel 1 goto obca_historia
set ZA=0
for /f %%i in ('git rev-list --count HEAD..origin/main 2^>nul') do set ZA=%%i
if not "%ZA%"=="0" goto trzeba_pobrac

:wysylaj_teraz
echo.
echo  Wysylam na GitHuba...
echo  Jesli to pierwszy raz, git otworzy przegladarke i poprosi o
echo  zalogowanie. To jedyny taki raz.
echo.
git push -u origin main
if errorlevel 1 goto nie_poszlo
goto udalo_sie

:trzeba_pobrac
echo.
echo  Na GitHubie jest %ZA% zmian, ktorych nie masz u siebie.
echo  Pobieram je i dokladam Twoje na wierzch...
git pull --rebase origin main
if errorlevel 1 goto konflikt
git push -u origin main
if errorlevel 1 goto nie_poszlo
goto udalo_sie

:obca_historia
echo.
echo  === HISTORIA NA GITHUBIE NIE PASUJE DO TEJ TUTAJ ===
echo.
echo  Git nie widzi wspolnego punktu miedzy tym folderem a GitHubem.
echo  Zwykle znaczy to, ze ten folder powstal na nowo - z ZIP-a albo
echo  przez "Sprawdz aktualizacje" - i dostal wlasna, osobna historie.
echo.
echo  Moge to naprawic bezpiecznie: wezme historie z GitHuba i doloze
echo  Twoje obecne pliki jako nowa wersje na jej wierzchu. Zadna
echo  poprzednia wersja z GitHuba nie zginie. Twoje pliki na dysku
echo  zostaja dokladnie takie, jakie sa.
echo.
set ODP=n
set /p ODP=  Zrobic to teraz? [t/n]: 
if /i not "%ODP%"=="t" goto recznie
echo.
git fetch origin main
git reset --mixed FETCH_HEAD
git add -A
git commit -m "Rybak %WERSJA%"
git push -u origin main
if errorlevel 1 goto nie_poszlo
goto udalo_sie

:recznie
echo.
echo  Dobrze, nic nie ruszam. Jesli to kopia programu, a nie komputer
echo  autorski - skasuj tu ukryty folder .git  . Aktualizacje przychodza
echo  przyciskiem "Sprawdz aktualizacje" i gita nie wymagaja.
echo.
echo  NIE uzywaj  --force  . Skasowalby wszystkie wersje na GitHubie.
goto koniec

:konflikt
echo.
echo  Te same pliki zmienily sie w dwoch miejscach naraz i git nie wie,
echo  ktora wersja jest wlasciwa. Wpisz w tym oknie:
echo      git rebase --abort
echo  a potem powiedz mi, co bylo zmieniane na drugim komputerze.
goto koniec

:blad_zapisu
echo.
echo  Git nie mogl zapisac zmian. Przeczytaj jego komunikat powyzej.
echo  Jesli pisze o pliku  index.lock  - zamknij wszystkie okna gita
echo  i programow, ktore go uzywaja, i uruchom ten plik jeszcze raz.
goto koniec

:udalo_sie
echo.
echo  === GOTOWE ===
echo  Wersja %WERSJA% jest na GitHubie. Na kazdym innym komputerze
echo  wystarczy teraz kliknac "Sprawdz aktualizacje".
goto koniec

:zly_folder
echo  Ten plik musi lezec w folderze programu, obok rybak.py
echo.
echo  Najczestsza przyczyna: uruchamiasz go prosto z ZIP-a. Rozpakuj
echo  caly ZIP na dysk i uruchom z rozpakowanego folderu.
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
echo    3. Przeciagnij tam zawartosc tego folderu
echo    4. Na dole kliknij "Commit changes"
goto koniec

:nie_poszlo
echo.
echo  Wysylka nie powiodla sie. Przeczytaj komunikat gita powyzej.
echo  Najczestsze powody:
echo    - git poprosil o zalogowanie, a okno zostalo zamkniete
echo    - brak internetu albo blokuje go firmowy proxy lub VPN
echo    - zly adres repozytorium: %REPO%

:koniec
echo.
pause
