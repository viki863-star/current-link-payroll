# PowerShell script to check technicians table schema
$dbPath = "payroll.db"

if (-not (Test-Path $dbPath)) {
    Write-Host "Database file $dbPath not found" -ForegroundColor Red
    exit 1
}

# Use sqlite3 command if available
$sqliteCmd = Get-Command sqlite3 -ErrorAction SilentlyContinue
if (-not $sqliteCmd) {
    Write-Host "sqlite3 command not found. Trying to use Python instead..." -ForegroundColor Yellow
    
    # Try Python
    $pythonOutput = python -c "
import sqlite3
conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(technicians)')
columns = cursor.fetchall()
print('Technicians table columns:')
for col in columns:
    print(f'{col[1]}|{col[2]}|{col[3]}')
conn.close()
" 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host $pythonOutput
    } else {
        Write-Host "Failed to check schema. Please install sqlite3 or ensure Python is available." -ForegroundColor Red
    }
    exit
}

# Use sqlite3
Write-Host "Technicians table schema:" -ForegroundColor Green
Write-Host "-------------------------" -ForegroundColor Green
sqlite3 $dbPath ".schema technicians"

Write-Host "`nColumn details:" -ForegroundColor Green
Write-Host "---------------" -ForegroundColor Green
sqlite3 $dbPath "PRAGMA table_info(technicians);"

Write-Host "`nSample data (first 3 rows):" -ForegroundColor Green
Write-Host "---------------------------" -ForegroundColor Green
sqlite3 $dbPath "SELECT technician_code, party_code, user_id, status FROM technicians LIMIT 3;"