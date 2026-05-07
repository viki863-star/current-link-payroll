# SSH deployment script
$server = "207.180.245.64"
$password = "CurrentLink2026Safe95"
$projectPath = "/opt/current-link/app"

# Create backup
$backupName = "app_backup_$(Get-Date -Format 'yyyy-MM-dd_HHmm')"
Write-Host "Creating backup: $backupName"

# We'll use plink if available, otherwise try ssh with expect
$commands = @"
cd /opt/current-link
cp -r app $backupName
cd app
git fetch origin main
git reset --hard origin/main
systemctl restart current-link
systemctl status current-link --no-pager -l
curl -I http://127.0.0.1:5000/login
"@

# Save commands to a file
$commands | Out-File -FilePath deploy_commands.txt -Encoding ASCII

Write-Host "Commands saved to deploy_commands.txt"
Write-Host "To execute manually, run:"
Write-Host "ssh root@$server"
Write-Host "Then run the commands from deploy_commands.txt"