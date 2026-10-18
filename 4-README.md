# Roostlink

Turn your Pi into a Wi-Fi hotspot and back again, on demand. Fullscreen
terminal UI, no NetworkManager - it drives `hostapd` and `dnsmasq`
directly and always knows how to put your home Wi-Fi back.

## What it does

- **Enable hotspot** (`e`, press twice within 8 seconds to confirm): takes
  the Pi's Wi-Fi card off your home network, gives it a static address
  (192.168.4.1), starts hostapd (WPA2) and dnsmasq (DHCP), and optionally
  NAT-shares the Pi's ethernet uplink so hotspot clients get internet.
- **Off switch** (`o`): stops hostapd/dnsmasq, clears the static address,
  turns packet forwarding back off, and restarts the normal Wi-Fi client
  so the Pi rejoins your home network (give it ~15 seconds).
- **Live status**: current mode, SSID/channel, connected hotspot clients
  (from the dnsmasq lease file), and whether the client link is up.
- **Configure** (`c`): SSID, WPA2 passphrase, channel, and whether to
  share the ethernet uplink. Saved to `/root/roostlink/config.json`.

## Safety

- Enabling the hotspot **drops the Pi's own Wi-Fi connection**. The UI
  says so and requires two keypresses; never enable it while you are only
  connected to the Pi over that same Wi-Fi.
- Nothing starts at boot. Roostlink only acts when you press keys.
- `ROOSTLINK_DRY_RUN=1 python3 roostlink.py` runs the full UI but prints
  the shell plan instead of executing it - good for a first look.
- You can also read the exact plans without the UI:
  `python3 roostlink.py --dump-plan --enable` and `--dump-plan`.

## Install (Pi App Store)

Install through the Pi App Store, or:

```sh
sudo bash app-store.sh install   # checks Python/curses, compiles sources
sudo python3 roostlink.py        # or: bash app-store.sh run
```

`hostapd`, `dnsmasq` and `iw` are installed by `apt` the first time you
actually enable the hotspot (not at app install time).

## Tests

```sh
python3 test_roostlink.py   # unit tests (plans, configs, leases)
python3 test_pty.py         # fullscreen dry-run walkthrough in a pty
```

MIT license, copyright Greenisus1. Built with AI assistance from my design.
