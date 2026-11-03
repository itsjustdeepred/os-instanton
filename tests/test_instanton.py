"""
Offline tests for the Instant On collector. They use anonymized data
captured from a 1960 switch and an AP25, and never touch the network.

    python3 -m unittest discover -s tests
"""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'src', 'opnsense', 'scripts', 'instanton'))

from lib import ap as aplib  # noqa: E402
from lib import collector, hostinfo  # noqa: E402
from lib import switch as swlib  # noqa: E402
from lib.config import Config  # noqa: E402


def fixture(name):
    with open(os.path.join(HERE, 'fixtures', name)) as fh:
        return fh.read()


class RsaTest(unittest.TestCase):
    @staticmethod
    def _prime(start):
        def probable_prime(n):
            if n % 2 == 0:
                return False
            d, r = n - 1, 0
            while d % 2 == 0:
                d //= 2
                r += 1
            for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
                x = pow(a, d, n)
                if x in (1, n - 1):
                    continue
                for _ in range(r - 1):
                    x = pow(x, 2, n)
                    if x == n - 1:
                        break
                else:
                    return False
            return True
        n = start | 1
        while not probable_prime(n):
            n += 2
        return n

    def test_roundtrip(self):
        p, q = self._prime(3 ** 330), self._prime(7 ** 190)
        n, e = p * q, 65537
        d = pow(e, -1, (p - 1) * (q - 1))
        msg = b'user=admin&password=s%40fe&ssd=true&token=abc&'
        cipher = int(swlib.rsa_pkcs1_v15_encrypt(msg, n, e), 16)
        block = pow(cipher, d, n).to_bytes((n.bit_length() + 7) // 8, 'big')
        self.assertEqual(block[:2], b'\x00\x02')
        self.assertEqual(block[block.index(b'\x00', 2) + 1:], msg)

    def test_parse_pkcs1_key(self):
        # PKCS#1 RSAPublicKey: SEQUENCE { INTEGER n, INTEGER e }
        import base64
        n, e = 0xC0FFEE1234567890ABCDEF, 65537
        nb = n.to_bytes(11, 'big')
        eb = e.to_bytes(3, 'big')
        body = b'\x02' + bytes([len(nb) + 1]) + b'\x00' + nb + b'\x02\x03' + eb
        der = b'\x30' + bytes([len(body)]) + body
        pem = '-----BEGIN RSA PUBLIC KEY-----\n%s\n-----END RSA PUBLIC KEY-----' % base64.b64encode(der).decode()
        self.assertEqual(swlib.parse_rsa_public_key(pem), (n, e))


class ApTest(unittest.TestCase):
    def test_parse_debug_info(self):
        info = aplib.parse_debug_info(fixture('ap_debug_info.xml'))
        self.assertEqual(info['model'], 'AP25')
        self.assertEqual(info['firmware'], '3.4.2.0')
        self.assertFalse(info['master'])
        self.assertEqual(info['ntp_status'], 'ERROR')
        self.assertTrue(info['crashed'])
        self.assertEqual(info['reboot_cause'], 'Panic: assert Warm-reset')


class HostinfoTest(unittest.TestCase):
    def test_mac_helpers(self):
        self.assertEqual(hostinfo.norm_mac('AA-BB-CC-0D-0E-0F'), 'aa:bb:cc:0d:0e:0f')
        self.assertEqual(hostinfo.norm_mac('aabb.cc0d.0e0f'), 'aa:bb:cc:0d:0e:0f')
        self.assertTrue(hostinfo.is_random_mac('da:a1:19:00:00:01'))
        self.assertFalse(hostinfo.is_random_mac('00:11:32:00:00:01'))

    def test_lease_parsers(self):
        with tempfile.TemporaryDirectory() as tmp:
            isc = os.path.join(tmp, 'dhcpd.leases')
            with open(isc, 'w') as fh:
                fh.write('lease 192.0.2.10 {\n  binding state active;\n  hardware ethernet 00:11:22:33:44:55;\n'
                                 '  client-hostname "nas";\n}\nlease 192.0.2.11 {\n  binding state free;\n'
                                 '  hardware ethernet 00:11:22:33:44:66;\n}\n')
            kea = os.path.join(tmp, 'kea.csv')
            with open(kea, 'w') as fh:
                fh.write('address,hwaddr,client_id,valid_lifetime,expire,subnet_id,fqdn_fwd,fqdn_rev,hostname,state\n'
                                 '192.0.2.20,00:11:22:33:44:77,,3600,%d,1,0,0,printer.,0\n' % (time.time() + 600))
            dnsm = os.path.join(tmp, 'dnsmasq.leases')
            with open(dnsm, 'w') as fh:
                fh.write('%d 00:11:22:33:44:88 192.0.2.30 phone 01:00:11:22:33:44:88\n' % (time.time() + 600))
            self.assertEqual(hostinfo.isc_leases(isc), {'00:11:22:33:44:55': {'ip': '192.0.2.10', 'hostname': 'nas', 'source': 'dhcp'}})
            self.assertEqual(hostinfo.kea_leases(kea)['00:11:22:33:44:77']['hostname'], 'printer')
            self.assertEqual(hostinfo.dnsmasq_leases(dnsm)['00:11:22:33:44:88']['ip'], '192.0.2.30')

    def test_static_mappings(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = os.path.join(tmp, 'config.xml')
            with open(cfg, 'w') as fh:
                fh.write('<opnsense><dhcpd><lan><staticmap><mac>00:aa:bb:cc:dd:ee</mac><ipaddr>192.0.2.5</ipaddr>'
                                 '<hostname>tv</hostname><descr>Living room TV</descr></staticmap></lan></dhcpd>'
                                 '<dnsmasq><hosts><host>cam</host><ip>192.0.2.6</ip><hwaddr>00:aa:bb:cc:dd:ff</hwaddr>'
                                 '<descr>Camera</descr></hosts></dnsmasq></opnsense>')
            res = hostinfo.static_mappings(cfg)
            self.assertEqual(res['00:aa:bb:cc:dd:ee']['description'], 'Living room TV')
            self.assertEqual(res['00:aa:bb:cc:dd:ff']['hostname'], 'cam')


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, 'state')
        conf = os.path.join(self.tmp.name, 'instanton.conf')
        with open(conf, 'w') as fh:
            fh.write('[general]\nenabled=1\n[switch]\nhost=192.0.2.2\nusername=u\npassword=p\n'
                              '[aps]\nenabled=1\ndiscover=1\n')
        self.cfg = Config(conf)
        self.raw = json.loads(fixture('switch_raw.json'))
        self.patches = [
            mock.patch.object(collector, 'STATE_DIR', self.state_dir),
            mock.patch('lib.config.STATE_DIR', self.state_dir),
            mock.patch.object(collector, 'fetch_switch_raw', lambda cfg, persistent: json.loads(json.dumps(self.raw))),
            mock.patch.object(collector.aplib, 'read_ap',
                              lambda host, port=8080: aplib.parse_debug_info(fixture('ap_debug_info.xml'))),
            mock.patch.object(collector.hostinfo, 'collect', lambda: {}),
            mock.patch.object(collector, 'firewall_macs', lambda: set()),
            mock.patch.object(collector, 'log', lambda level, msg: None),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_full_run(self):
        state = collector.run(self.cfg)
        sw = state['switch']
        self.assertTrue(sw['online'])
        self.assertEqual(len(sw['ports']), 52)
        self.assertEqual(sw['ports'][0]['name'], '1/1')
        self.assertEqual(state['summary']['aps_total'], 5)
        roles = {p['name']: p.get('role') for p in sw['ports']}
        self.assertEqual(roles['1/1'], 'ap')
        self.assertEqual(roles['1/51'], 'uplink')  # description mentions OPNsense
        self.assertTrue(any(c['connection'] == 'wireless' for c in state['clients']))
        self.assertFalse(any(c['port'] == '1/51' for c in state['clients']))
        titles = [i['title'] for i in state['insights']]
        self.assertIn('Switch clock is wrong', titles)
        self.assertTrue(any(t.startswith('Time sync failing') for t in titles))
        # log is newest first
        times = [entry['time'] for entry in sw['log'] if entry['time']]
        self.assertEqual(times, sorted(times, reverse=True))

    def test_second_run_rates_and_events(self):
        collector.run(self.cfg)
        port = next(p for p in self.raw['Standard802_3List']['Entry'] if p['interfaceName'] == '1/5')
        port['linkState'] = '2'
        for s in self.raw['StatisticsList']['InterfaceStatisticsEntry']:
            if s['interfaceName'] == '1/1':
                s['receivePacketByteCount'] = str(int(s['receivePacketByteCount']) + 10 ** 6)
        real_time = time.time
        with mock.patch.object(collector.time, 'time', lambda: real_time() + 60):
            state = collector.run(self.cfg)
        p11 = next(p for p in state['switch']['ports'] if p['name'] == '1/1')
        self.assertIsNotNone(p11['rx_bps'])
        with open(os.path.join(self.state_dir, 'events.json')) as fh:
            events = json.load(fh)
        self.assertTrue(any('1/5' in e['message'] and 'down' in e['message'] for e in events))

    def test_switch_failure_is_reported(self):
        def boom(cfg, persistent):
            raise swlib.SwitchError('login failed: invalid username or password')
        with mock.patch.object(collector, 'fetch_switch_raw', boom):
            state = collector.run(self.cfg)
        self.assertFalse(state['sources']['switch']['ok'])
        self.assertIn('invalid username', state['sources']['switch']['error'])
        self.assertFalse(state['summary']['switch_online'])


if __name__ == '__main__':
    unittest.main()
