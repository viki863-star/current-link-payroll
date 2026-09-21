import paramiko, sys

host = '207.180.245.64'
user = 'root'
password = 'CurrentLink2026Safe95'

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, 22, user, password, timeout=15)

cmd = sys.stdin.read()
stdin, stdout, stderr = client.exec_command(cmd, timeout=300)
out = stdout.read().decode()
err = stderr.read().decode()
if out:
    print(out)
if err:
    print('[ERR]', err, file=sys.stderr)
client.close()
