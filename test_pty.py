"""PTY smoke test: dry-run UI boots, arm+confirm prints the plan, quits clean."""
import os, pty, re, select, subprocess, sys, time

env = dict(os.environ, ROOSTLINK_DRY_RUN="1", TERM="xterm-256color",
           LINES="30", COLUMNS="100")
pid, fd = pty.fork()
if pid == 0:
    os.execvpe(sys.executable, [sys.executable, "roostlink.py"], env)

out = b""
def pump(t):
    global out
    end = time.time() + t
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try: out += os.read(fd, 65536)
            except OSError: break

fail = []
pump(2.0)
if not re.search(rb"ROOSTLINK v1\.0\.0", out): fail.append("title bar")
if not re.search(rb"DRY RUN", out): fail.append("dry-run marker")
os.write(fd, b"e")          # arm (no passphrase set yet -> should warn, not arm)
pump(1.0)
os.write(fd, b"c")          # configure
pump(1.0)
os.write(fd, b"TestNest\n") # SSID
pump(0.8)
os.write(fd, b"chickadee42\n")  # passphrase
pump(0.8)
os.write(fd, b"\n\n")       # channel + uplink defaults
pump(1.0)
os.write(fd, b"e")          # arm
pump(0.8)
os.write(fd, b"e")          # confirm -> dry-run plan to stderr (same pty)
pump(1.5)
if not re.search(rb"ip addr add 192\.168\.4\.1/24", out): fail.append("enable plan")
os.write(fd, b"o")          # off switch, dry-run
pump(1.0)
if not re.search(rb"restart wpa_supplicant", out): fail.append("restore plan")
os.write(fd, b"q")
pump(1.0)
wp, status = os.waitpid(pid, os.WNOHANG)
if wp == 0:
    try:
        os.kill(pid, 9); os.waitpid(pid, 0)
    except ProcessLookupError:
        pass
    fail.append("did not quit")
if fail:
    print("PTY FAIL:", ", ".join(fail)); sys.exit(1)
print("PTY PASS")
