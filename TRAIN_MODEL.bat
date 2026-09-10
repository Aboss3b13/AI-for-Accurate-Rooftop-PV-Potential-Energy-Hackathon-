@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Run START_SOLARFIT.bat first.
 pause
 exit /b 1
)
if not exist "data\yolo\dataset.yaml" (
 echo Download and extract the Kaggle dataset into data\raw, then run:
 echo .venv\Scripts\python.exe training\prepare_dataset.py
 pause
 exit /b 1
)
".venv\Scripts\python.exe" training\train_yolo.py --install %*
pause
