import importlib.util, os, tempfile, unittest

os.environ["ROOSTLINK_DRY_RUN"] = "1"
spec = importlib.util.spec_from_file_location(
    "roostlink", os.path.join(os.path.dirname(__file__), "roostlink.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

CFG = dict(r.DEFAULTS, psk="hunter2hunter2")


class TestConfs(unittest.TestCase):
    def test_hostapd_conf(self):
        c = r.render_hostapd_conf(CFG)
        self.assertIn("ssid=PiRoost", c)
        self.assertIn("wpa=2", c)
        self.assertIn("wpa_passphrase=hunter2hunter2", c)
        self.assertIn("channel=7", c)
        self.assertIn("interface=wlan0", c)

    def test_dnsmasq_conf(self):
        c = r.render_dnsmasq_conf(CFG)
        self.assertIn("dhcp-range=192.168.4.10,192.168.4.200", c)
        self.assertIn("interface=wlan0", c)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            old = r.CFG_PATH
            r.CFG_PATH = p
            try:
                cfg = dict(CFG, ssid="Barn")
                r.save_cfg(cfg)
                back = r.load_cfg()
            finally:
                r.CFG_PATH = old
            self.assertEqual(back["ssid"], "Barn")
            self.assertEqual(back["psk"], CFG["psk"])


class TestPlans(unittest.TestCase):
    def flat(self, plan):
        return [" ".join(c) for c in plan]

    def test_enable_starts_services_after_ip(self):
        plan = self.flat(r.enable_plan(CFG))
        self.assertLess(plan.index("ip addr add 192.168.4.1/24 dev wlan0"),
                        plan.index("systemctl start hostapd"))
        self.assertLess(plan.index("systemctl start hostapd"),
                        plan.index("systemctl start dnsmasq"))

    def test_enable_shares_uplink(self):
        plan = self.flat(r.enable_plan(CFG))
        self.assertTrue(any("MASQUERADE" in s for s in plan))
        cfg = dict(CFG, share_uplink=False)
        plan = self.flat(r.enable_plan(cfg))
        self.assertFalse(any("MASQUERADE" in s for s in plan))

    def test_disable_always_restores_client(self):
        for share in (True, False):
            plan = self.flat(r.disable_plan(dict(CFG, share_uplink=share)))
            self.assertIn("systemctl stop hostapd", plan[1])
            self.assertTrue(any("systemctl restart wpa_supplicant" in s for s in plan))
            self.assertTrue(any("dhcpcd" in s or "ifup" in s for s in plan))
            self.assertLess(plan.index("systemctl stop dnsmasq"),
                            next(i for i, s in enumerate(plan)
                                 if "wpa_supplicant" in s))

    def test_disable_never_enables_forwarding(self):
        plan = self.flat(r.disable_plan(CFG))
        self.assertTrue(any("ip_forward=0" in s for s in plan))
        self.assertFalse(any("ip_forward=1" in s for s in plan))

    def test_dry_run_executes_nothing(self):
        ok, err = r.execute(r.enable_plan(CFG))
        self.assertTrue(ok)
        self.assertFalse(os.path.exists("/etc/hostapd/hostapd.conf"))


class TestClients(unittest.TestCase):
    def test_parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "leases")
            open(p, "w").write(
                "1729000000 aa:bb:cc:dd:ee:ff 192.168.4.10 phone 01:aa:bb\n"
                "1729000001 11:22:33:44:55:66 192.168.4.11 * *\n")
            old = r.LEASES
            r.LEASES = [p]
            try:
                cl = r.clients()
            finally:
                r.LEASES = old
            self.assertEqual(len(cl), 2)
            self.assertIn(("11:22:33:44:55:66", "192.168.4.11", "*"), cl)


if __name__ == "__main__":
    unittest.main()
