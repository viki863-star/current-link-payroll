import paramiko, sys, time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

host = '207.180.245.64'
port = 22
user = 'root'
password = 'CurrentLink2026Safe95'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, port, user, password, timeout=15)

def run(cmd, timeout=30):
    print(f"$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace').strip()
    err = stderr.read().decode('utf-8', 'replace').strip()
    if out:
        print(out)
    if err:
        print('[ERR]', err, file=sys.stderr)
    return stdout.channel.recv_exit_status()

run('cd /opt/current-link && echo "Backing up..." && BACKUP_NAME="app_backup_$(date +%F_%H%M)" && cp -r app "$BACKUP_NAME" && ls -dt app_backup_* | tail -n +6 | xargs rm -rf && echo "Backup done: $BACKUP_NAME"', timeout=180)
run('cd /opt/current-link/app && git fetch origin main && git reset --hard origin/main && echo "Code updated: $(git log --oneline -1)"')
run('cd /opt/current-link/app && .venv/bin/pip install -r requirements.txt --quiet && echo "Dependencies up to date"', timeout=180)
run('systemctl restart current-link')
time.sleep(3)
run('systemctl status current-link --no-pager -l 2>&1 | tail -20')
code = run('curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:7860/login')
print(f"\nHTTP Status: {code}")

client.close()
print("\nDeployment complete!")
