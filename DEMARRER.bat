@echo off
chcp 65001 >nul
title SIREPH - serveur
cd /d "%~dp0"

echo ============================================================
echo   SIREPH — demarrage
echo ============================================================
echo.

REM --- Environnement Python -----------------------------------------------
if not exist "venv\Scripts\python.exe" (
    echo [1/4] Creation de l'environnement Python...
    python -m venv venv
    if errorlevel 1 goto erreur_python
    venv\Scripts\python.exe -m pip install --quiet --upgrade pip
    venv\Scripts\python.exe -m pip install --quiet -r requirements.txt
    if errorlevel 1 goto erreur
) else (
    echo [1/4] Environnement Python : OK
)

REM --- Base de donnees -----------------------------------------------------
if not exist "instance\sireph.db" (
    echo [2/4] Creation de la base de donnees et des donnees de demonstration...
    venv\Scripts\python.exe seed.py
    if errorlevel 1 goto erreur
) else (
    echo [2/4] Base de donnees : OK
)

REM --- Comptes de tous les roles (idempotent) ------------------------------
echo [3/4] Verification des comptes de demonstration...
venv\Scripts\python.exe seed_comptes.py >nul
if errorlevel 1 goto erreur

REM --- Serveur -------------------------------------------------------------
echo [4/4] Demarrage du serveur...
echo.
start "" http://localhost:5000/acces
venv\Scripts\python.exe run_lan.py
goto fin

:erreur_python
echo.
echo ERREUR : Python n'est pas installe ou pas dans le PATH.
echo Installez Python 3 depuis https://www.python.org/downloads/
echo en cochant "Add Python to PATH", puis relancez ce fichier.
echo.
pause
exit /b 1

:erreur
echo.
echo ERREUR pendant la preparation. Le detail est affiche ci-dessus.
echo.
pause
exit /b 1

:fin
echo.
echo Le serveur s'est arrete.
pause
