#!/bin/bash

# Deploy script for Current-Link Payroll
SERVER="207.180.245.64"
PASSWORD="CurrentLink2026Safe95"
PROJECT_PATH="/opt/current-link/app"

echo "=== Deploying to Production Server ==="
echo "Server: $SERVER"
echo ""

# Step 1: SSH and deploy
echo "1. Connecting to server..."
sshpass -p "$PASSWORD" ssh -o StrictHostKeyChecking=no root@$SERVER << 'EOF'

echo "2. Creating backup..."
cd /opt/current-link
BACKUP_NAME="app_backup_$(date +%F_%H%M)"
cp -r app "$BACKUP_NAME"
echo "Backup created: $BACKUP_NAME"

echo "3. Deploying latest code..."
cd app
git fetch origin main
git reset --hard origin/main
echo "Code updated to latest commit: $(git log --oneline -1)"

echo "4. Restarting service..."
systemctl restart current-link
sleep 3

echo "5. Checking service status..."
systemctl status current-link --no-pager -l

echo "6. Testing application..."
curl -I http://127.0.0.1:5000/login

echo ""
echo "=== Deployment Complete ==="
echo "Backup: $BACKUP_NAME"
echo "Service: current-link"
echo "Check if application is running properly."
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Deployment successful!"
    echo "You can check the application at: http://207.180.245.64:5000"
else
    echo ""
    echo "❌ Deployment failed. Check SSH connection and credentials."
fi