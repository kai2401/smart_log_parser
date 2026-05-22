@echo off
setlocal EnableDelayedExpansion

echo ======================================================
echo  Smart Tool Log Parser - CLI Demonstration Script
echo ======================================================
echo.

echo 1. Clearing any existing database records...
python cli.py clear --yes
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 2. Generating synthetic logs and ingesting them...
python cli.py generate --ingest
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 3. Showing overall statistics...
python cli.py stats
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 4. Querying logs for errors...
python cli.py query --severity ERROR --limit 5
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 5. Searching logs for specific text (e.g., 'vacuum')...
python cli.py query --search "vacuum" --limit 5
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 6. Exporting error logs to CSV...
python cli.py export demo_errors.csv --severity ERROR
if %errorlevel% neq 0 exit /b %errorlevel%
echo Checking exported file:
dir demo_errors.csv
echo.

echo 7. Viewing active format templates...
python cli.py templates
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo 8. Running AI Analysis (requires OPENAI_API_KEY in .env)...
python cli.py analyze --question "What are the most critical errors in these logs and how can we prevent them?"
if %errorlevel% neq 0 exit /b %errorlevel%
echo.

echo ======================================================
echo  Demo completed successfully!
echo ======================================================
