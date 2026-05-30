# PowerShell script to fix NOT NULL constraints in technicians table
Write-Host "Fixing NOT NULL constraints in technicians table..." -ForegroundColor Yellow

$dbPath = "payroll.db"

# Check if SQLite is available
try {
    # Try to use System.Data.SQLite via .NET
    Add-Type -Path "System.Data.SQLite" -ErrorAction Stop
} catch {
    Write-Host "SQLite .NET assembly not found, trying alternative approach..." -ForegroundColor Yellow
}

# Use a simple approach with sqlite3.exe if available
$sqliteExe = "sqlite3"
if (Get-Command $sqliteExe -ErrorAction SilentlyContinue) {
    Write-Host "Found sqlite3.exe, running SQL commands..." -ForegroundColor Green
    
    # Check current schema
    Write-Host "`nCurrent technicians table schema:" -ForegroundColor Cyan
    & sqlite3 $dbPath ".schema technicians"
    
    # Check if columns have NOT NULL constraints
    Write-Host "`nChecking column constraints..." -ForegroundColor Cyan
    & sqlite3 $dbPath "PRAGMA table_info(technicians);"
    
    # SQLite doesn't support ALTER COLUMN to remove NOT NULL directly
    # We need to recreate the table
    Write-Host "`nRecreating technicians table without NOT NULL constraints..." -ForegroundColor Yellow
    
    # Create a backup of the table
    & sqlite3 $dbPath @"
-- Create a temporary table with the new schema
CREATE TABLE technicians_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    technician_code TEXT UNIQUE,
    party_code TEXT,
    user_id TEXT UNIQUE,
    password_hash TEXT,
    phone_number TEXT,
    specialization TEXT,
    status TEXT DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code) ON DELETE SET NULL
);

-- Copy data from old table
INSERT INTO technicians_new 
SELECT * FROM technicians;

-- Drop old table
DROP TABLE technicians;

-- Rename new table to original name
ALTER TABLE technicians_new RENAME TO technicians;

-- Recreate indexes if any
CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_user_id ON technicians(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_technician_code ON technicians(technician_code);
"@
    
    Write-Host "Table recreation completed." -ForegroundColor Green
    
    # Verify the new schema
    Write-Host "`nNew technicians table schema:" -ForegroundColor Cyan
    & sqlite3 $dbPath ".schema technicians"
    
} else {
    Write-Host "sqlite3.exe not found in PATH. Please install SQLite or run the migration manually." -ForegroundColor Red
    Write-Host "Manual steps:" -ForegroundColor Yellow
    Write-Host "1. Open payroll.db with SQLite browser" -ForegroundColor Yellow
    Write-Host "2. Run the following SQL:" -ForegroundColor Yellow
    Write-Host @"
-- Create a temporary table with the new schema
CREATE TABLE technicians_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    technician_code TEXT UNIQUE,
    party_code TEXT,
    user_id TEXT UNIQUE,
    password_hash TEXT,
    phone_number TEXT,
    specialization TEXT,
    status TEXT DEFAULT 'Active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(party_code) REFERENCES parties(party_code) ON DELETE SET NULL
);

-- Copy data from old table
INSERT INTO technicians_new 
SELECT * FROM technicians;

-- Drop old table
DROP TABLE technicians;

-- Rename new table to original name
ALTER TABLE technicians_new RENAME TO technicians;

-- Recreate indexes if any
CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_user_id ON technicians(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technicians_technician_code ON technicians(technician_code);
"@
}

Write-Host "`nScript completed." -ForegroundColor Green