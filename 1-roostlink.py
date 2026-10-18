#!/usr/bin/env python3
"""Roostlink - turn a Pi into a Wi-Fi hotspot and back, on demand.

Fullscreen terminal UI. No NetworkManager: drives hostapd + dnsmasq
directly. Enabling the hotspot cuts the Pi's own Wi-Fi client link, so
activation is two-key confirmed and there is a one-key off switch that
restores the home Wi-Fi client.

Set ROOSTLINK_DRY_RUN=1 to print the exact shell plan without running it.
MIT license, copyright Greenisus1. Built with AI assistance from my design.
"""
import curses, json, os, re, subprocess, sys, time

VERSION = "1.0.0"
APP_DIR = "/root/roostlink"
CFG_PATH = os.path.join(APP_DIR, "config.json")
LEASES = ["/var/lib/misc/dnsmasq.leases", "/run/dnsmasq/leases",
          "/var/lib/NetworkManager/dnsmasq.leases"]
AP_IP = "192.168.4.1"
DRY = os.environ.get("ROOSTLINK_DRY_RUN") == "1"
if DRY:
    APP_DIR = "/tmp/roostlink-dryrun"
    CFG_PATH = os.path.join(APP_DIR, "config.json")

DEFAULTS = {"iface": "wlan0", "ssid": "PiRoost", "psk": "", "channel": "7",
            "country": "US", "share_uplink": True}


def load_cfg():
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.load(open(CFG_PATH)))
    except Exception:
        pass
    return cfg


def save_cfg(cfg):
    os.makedirs(os.path.dirname(CFG_PATH), exist_ok=True)
    json.dump(cfg, open(CFG_PATH, "w"), indent=2)


def run(cmd, check=False):
    """Run a shell command (list form). Returns (rc, output)."""
    if DRY:
        return 0, ""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (p.stdout or "") + (p.stderr or "")
        if check and p.returncode:
            raise RuntimeError(out.strip() or f"rc={p.returncode}")
        return p.returncode, out
    except FileNotFoundError:
        if check:
            raise
        return 127, ""


def sh(cmdline, check=False):
    """Run a shell string (for pipes/redirection in the plan)."""
    if DRY:
        return 0, ""
    p = subprocess.run(cmdline, shell=True, capture_output=True, text=True, timeout=60)
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode:
        raise RuntimeError(out.strip() or f"rc={p.returncode}")
    return p.returncode, out


def have(cmdname):
    return run(["sh", "-c", f"command -v {cmdname}"])[0] == 0


def hotspot_active(cfg):
    if DRY:
        return False
    return run(["systemctl", "is-active", "hostapd"])[1].strip() == "active"


def current_wifi(cfg):
    """(connected, ssid) of the client link."""
    if DRY:
        return False, ""
    rc, out = run(["iw", "dev", cfg["iface"], "link"])
    if rc or "Not connected" in out:
        return False, ""
    m = re.search(r"SSID:\s*(.+)", out)
    return True, (m.group(1).strip() if m else "?")


def clients():
    seen = set()
    for path in LEASES:
        try:
            for line in open(path):
                parts = line.split()
                if len(parts) >= 4:
                    seen.add((parts[1].lower(), parts[2], parts[3]))
        except Exception:
            pass
    return sorted(seen)


def render_hostapd_conf(cfg):
    return ("\n".join([
        f"interface={cfg['iface']}", "driver=nl80211",
        f"ssid={cfg['ssid']}", f"country_code={cfg['country']}",
        "hw_mode=g", f"channel={cfg['channel']}",
        "wmm_enabled=1", "auth_algs=1", "wpa=2",
        f"wpa_passphrase={cfg['psk']}", "wpa_key_mgmt=WPA-PSK",
        "rsn_pairwise=CCMP", ""]) + "\n")


def render_dnsmasq_conf(cfg):
    return ("\n".join([
        f"interface={cfg['iface']}", "bind-interfaces",
        "dhcp-range=192.168.4.10,192.168.4.200,255.255.255.0,24h",
        "domain-needed", "bogus-priv", ""]) + "\n")


def enable_plan(cfg):
    """Shell plan to bring the hotspot up. Client Wi-Fi goes down here."""
    steps = [
        ["systemctl", "stop", "dnsmasq"],
        ["systemctl", "stop", "hostapd"],
        ["sh", "-c", f"systemctl stop wpa_supplicant@{cfg['iface']} 2>/dev/null; true"],
        ["ip", "link", "set", cfg["iface"], "down"],
        ["ip", "addr", "flush", "dev", cfg["iface"]],
        ["ip", "link", "set", cfg["iface"], "up"],
        ["ip", "addr", "add", AP_IP + "/24", "dev", cfg["iface"]],
        ["systemctl", "unmask", "hostapd"],
        ["systemctl", "unmask", "dnsmasq"],
        ["systemctl", "start", "hostapd"],
        ["systemctl", "start", "dnsmasq"],
    ]
    if cfg["share_uplink"]:
        steps += [
            ["sysctl", "-w", "net.ipv4.ip_forward=1"],
            ["sh", "-c", "iptables -t nat -C POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null || "
                         "iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE"],
        ]
    return steps


def disable_plan(cfg):
    """Shell plan to restore the home Wi-Fi client. Never skips restore."""
    steps = [
        ["systemctl", "stop", "dnsmasq"],
        ["systemctl", "stop", "hostapd"],
        ["ip", "addr", "flush", "dev", cfg["iface"]],
        ["sh", "-c", "sysctl -w net.ipv4.ip_forward=0 >/dev/null; true"],
        ["sh", "-c", "iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE 2>/dev/null; true"],
    ]
    if cfg["share_uplink"]:
        steps = steps[:5]
    steps += [
        ["systemctl", "restart", "wpa_supplicant"],
        ["sh", "-c", "systemctl restart dhcpcd 2>/dev/null || "
                     "(command -v ifup >/dev/null && ifup " + cfg["iface"] + ") 2>/dev/null || true"],
    ]
    return steps


def write_confs(cfg):
    base = "/tmp/roostlink-dryrun" if DRY else APP_DIR
    os.makedirs(base, exist_ok=True)
    open(os.path.join(base, "hostapd.conf"), "w").write(render_hostapd_conf(cfg))
    open(os.path.join(base, "dnsmasq.conf"), "w").write(render_dnsmasq_conf(cfg))
    if DRY:
        return
    open("/etc/hostapd/hostapd.conf", "w").write(render_hostapd_conf(cfg))
    sh("grep -q '^DAEMON_CONF=' /etc/default/hostapd 2>/dev/null || "
       "echo 'DAEMON_CONF=\"/etc/hostapd/hostapd.conf\"' >> /etc/default/hostapd")
    open("/etc/dnsmasq.d/roostlink.conf", "w").write(render_dnsmasq_conf(cfg))


def execute(plan):
    for cmd in plan:
        if DRY:
            continue
        rc, out = run(cmd)
        if rc and cmd[0] not in ("sh",):
            return False, f"{' '.join(cmd)}: {out.strip()}"
    return True, ""


def ensure_deps():
    missing = [c for c in ("hostapd", "dnsmasq", "iw") if not have(c)]
    if missing and not DRY:
        sh("apt-get update -qq && apt-get install -y -qq hostapd dnsmasq iw")
    return [c for c in ("hostapd", "dnsmasq", "iw") if not have(c)] and not DRY


# ---------- curses UI ----------

def draw(scr, cfg, msg, armed):
    scr.erase()
    h, w = scr.getmaxyx()
    scr.addnstr(0, 0, f" ROOSTLINK v{VERSION} - Pi Wi-Fi hotspot ".ljust(w - 1, " "),
                w - 1, curses.A_REVERSE)
    on = hotspot_active(cfg)
    conn, ssid = current_wifi(cfg)
    state = "HOTSPOT ON" if on else ("client: " + ssid if conn else "idle")
    scr.addnstr(2, 2, f"State:    {state}{'  [DRY RUN]' if DRY else ''}", w - 4)
    scr.addnstr(3, 2, f"SSID:     {cfg['ssid']}   channel {cfg['channel']}   "
                      f"key {'set' if cfg['psk'] else 'NOT SET'}", w - 4)
    scr.addnstr(4, 2, f"AP addr:  {AP_IP}   share ethernet uplink: "
                      f"{'yes' if cfg['share_uplink'] else 'no'}", w - 4)
    cl = [] if DRY else clients()
    scr.addnstr(5, 2, f"Clients:  {len(cl)}" + ("  " + "  ".join(
        f"{ip}({name if name != '*' else mac})" for mac, ip, name in cl[:4]) if cl else ""),
        w - 4)
    scr.addnstr(7, 0, "-" * (w - 1), w - 1)
    keys = ("[e]nable hotspot (cuts Pi's Wi-Fi!)  [o]ff / restore home Wi-Fi  "
            "[c]onfigure  [r]efresh  [q]uit")
    scr.addnstr(h - 2, 0, keys[:w - 1], w - 1, curses.A_REVERSE)
    if armed:
        scr.addnstr(h - 3, 2, "ARMED: press e again within 8s to START the hotspot. "
                              "This drops the Pi's current Wi-Fi connection.",
                    w - 4, curses.A_BOLD)
    if msg:
        scr.addnstr(h - 4 if armed else h - 3, 2, msg, w - 4, curses.A_BOLD)
    scr.refresh()


def prompt(scr, label, secret=False):
    curses.echo(not secret)
    curses.curs_set(1)
    h, w = scr.getmaxyx()
    scr.addnstr(h - 5, 2, label + " ", w - 4, curses.A_BOLD)
    scr.refresh()
    try:
        val = scr.getstr(h - 5, 2 + len(label) + 1, 64).decode().strip()
    except Exception:
        val = ""
    curses.noecho()
    curses.curs_set(0)
    return val


def configure(scr, cfg, msg):
    v = prompt(scr, f"SSID [{cfg['ssid']}] (blank keeps):")
    if v:
        cfg["ssid"] = v
    v = prompt(scr, "WPA2 passphrase (>=8 chars, blank keeps) :", secret=True)
    if v:
        if len(v) < 8:
            return "Passphrase must be >= 8 chars - not saved."
        cfg["psk"] = v
    v = prompt(scr, f"Channel [{cfg['channel']}] (blank keeps):")
    if v:
        cfg["channel"] = v
    v = prompt(scr, f"Share ethernet uplink y/n "
                      f"[{'y' if cfg['share_uplink'] else 'n'}] (blank keeps):")
    if v.lower() in ("y", "n"):
        cfg["share_uplink"] = v.lower() == "y"
    save_cfg(cfg)
    return "Saved."


def main(scr):
    curses.curs_set(0)
    scr.timeout(2000)
    cfg = load_cfg()
    msg = ""
    if not cfg["psk"]:
        msg = "Set a passphrase with [c] before enabling."
    armed_at = 0.0
    while True:
        draw(scr, cfg, msg, time.time() - armed_at < 8)
        try:
            ch = scr.getch()
        except KeyboardInterrupt:
            break
        if ch == -1:
            if armed_at and time.time() - armed_at > 8:
                armed_at = 0.0
            continue
        c = chr(ch).lower() if 0 <= ch < 256 else ""
        if c == "q":
            break
        elif c == "r":
            msg = ""
        elif c == "c":
            msg = configure(scr, cfg, msg)
            armed_at = 0.0
        elif c == "e":
            if hotspot_active(cfg):
                msg = "Already on. [o] turns it off."
            elif not cfg["psk"]:
                msg = "Set a passphrase first ([c])."
            elif time.time() - armed_at < 8 and armed_at:
                armed_at = 0.0
                missing = ensure_deps()
                if missing:
                    msg = "Missing tools and apt install failed: " + " ".join(missing)
                else:
                    write_confs(cfg)
                    if DRY:
                        for cmd in enable_plan(cfg):
                            print("PLAN>", " ".join(cmd), file=sys.stderr)
                        msg = "DRY RUN: enable plan printed to stderr."
                    else:
                        ok, err = execute(enable_plan(cfg))
                        msg = "Hotspot ON." if ok else "Enable failed: " + err[:120]
            else:
                armed_at = time.time()
                msg = ""
        elif c == "o":
            armed_at = 0.0
            if DRY:
                for cmd in disable_plan(cfg):
                    print("PLAN>", " ".join(cmd), file=sys.stderr)
                msg = "DRY RUN: restore plan printed to stderr."
            else:
                ok, err = execute(disable_plan(cfg))
                msg = "Off - home Wi-Fi restoring (give it ~15s)." if ok else \
                      "Disable error: " + err[:120]


if __name__ == "__main__":
    if "--dump-plan" in sys.argv:
        cfg = load_cfg()
        cfg.setdefault("psk", "x" * 12) or cfg.update(psk=cfg["psk"] or "x" * 12)
        which = "enable" if "--enable" in sys.argv else "disable"
        for cmd in (enable_plan if which == "enable" else disable_plan)(cfg):
            print(" ".join(cmd))
        sys.exit(0)
    curses.wrapper(main)
