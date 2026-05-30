# PowerShell script to test technician system
$dbPath = "payroll.db"

if (-not (Test-Path $dbPath)) {
    Write-Host "Database file $dbPath not found" -ForegroundColor Red
    exit 1
}

# Try to use sqlite3 if available
$sqliteCmd = Get-Command sqlite3 -ErrorAction SilentlyContinue
if ($sqliteCmd) {
    Write-Host "Using sqlite3..." -ForegroundColor Green
    
    # Check maintenance_papers table
    Write-Host "`n=== Checking maintenance_papers table ==="
    $columns = sqlite3 $dbPath "PRAGMA table_info(maintenance_papers);"
    Write-Host $columns
    
    # Check if technician_code exists
    $hasTechCode = $columns | Select-String "technician_code"
    if ($hasTechCode) {
        Write-Host "✓ technician_code column exists" -ForegroundColor Green
    } else {
        Write-Host "✗ technician_code column NOT found" -ForegroundColor Red
    }
    
    # Check technicians table
    Write-Host "`n=== Checking technicians table ==="
    $techColumns = sqlite3 $dbPath "PRAGMA table_info(technicians);"
    Write-Host $techColumns
    
    # Check Amjad5 technician
    Write-Host "`n=== Checking technician Amjad5 ==="
    $tech = sqlite3 $dbPath "SELECT user_id, password_hash FROM technicians WHERE user_id = 'Amjad5';"
    if ($tech) {
        Write-Host "Found technician Amjad5:" -ForegroundColor Green
        Write-Host $tech
        
        # Check password hash
        $password = "1234"
        $hash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash([System.Text.Encoding]::UTF8.GetBytes($password))) -replace '-', '').ToLower()
        Write-Host "SHA-256 hash of '1234': $hash"
    } else {
        Write-Host "Technician Amjad5 not found" -ForegroundColor Yellow
    }
    
    # Test technician jobs query
    Write-Host "`n=== Testing technician jobs query ==="
    try {
        $jobs = sqlite3 $dbPath "SELECT mp.paper_no, mp.technician_code, mp.review_status, mp.payment_status FROM maintenance_papers mp WHERE mp.technician_code IS NOT NULL LIMIT 5;"
        if ($jobs) {
            Write-Host "Query successful:" -ForegroundColor Green
            Write-Host $jobs
        } else {
            Write-Host "No technician jobs found (query returned empty)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Query failed: $_" -ForegroundColor Red
    }
    
} else {
    Write-Host "sqlite3 not found. Trying Python..." -ForegroundColor Yellow
    
    # Try Python
    $pythonScript = @"
import sqlite3
import hashlib
import sys

conn = sqlite3.connect('payroll.db')
cursor = conn.cursor()

print("=== Checking maintenance_papers table ===")
cursor.execute("PRAGMA table_info(maintenance_papers)")
columns = cursor.fetchall()
for col in columns:
    print(f"{col[1]}|{col[2]}|{col[3]}")
    
has_tech_code = any(col[1] == 'technician_code' for col in columns)
print(f"\nHas technician_code: {has_tech_code}")

print("\n=== Checking technicians table ===")
cursor.execute("PRAGMA table_info(technicians)")
tech_columns = cursor.fetchall()
for col in tech_columns:
    print(f"{col[1]}|{col[2]}|{col[3]}")

print("\n=== Checking technician Amjad5 ===")
cursor.execute("SELECT user_id, password_hash FROM technicians WHERE user_id = ?", ('Amjad5',))
tech = cursor.fetchone()
if tech:
    user_id, password_hash = tech
    print(f"Found: {user_id}")
    print(f"Password hash: {password_hash[:20]}...")
    
    test_hash = hashlib.sha256('1234'.encode()).hexdigest()
    if password_hash == test_hash:
        print("Password hash matches '1234'")
    else:
        print(f"Password hash does NOT match '1234'")
        print(f"Expected: {test_hash}")
        print(f"Actual:   {password_hash}")
else:
    print("Technician Amjad5 not found")

print("\n=== Testing technician jobs query ===")
try:
    cursor.execute("SELECT mp.paper_no, mp.technician_code, mp.review_status, mp.payment_status FROM maintenance_papers mp WHERE mp.technician_code IS NOT NULL LIMIT 5")
    results = cursor.fetchall()
    print(f"Found {len(results)} records")
    for row in results:
        print(f"Paper: {row[0]}, Tech: {row[1]}, Status: {row[2]}, Payment: {row[3]}")
except Exception as e:
    print(f"Query failed: {e}")

conn.close()
"@
    
    $pythonOutput = python -c $pythonScript 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host $pythonOutput
    } else {
        Write-Host "Failed to run Python script" -ForegroundColor Red
    }
}