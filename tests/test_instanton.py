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

from lib import actions  # noqa: E402
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
            mock.patch.object(collector, 'fetch_switch_raw', lambda dev, persistent: json.loads(json.dumps(self.raw))),
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
        sw = state['switches'][0]
        self.assertEqual(sw['id'], 'default')
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
        # the fixture access points run with a clock several hours off
        self.assertTrue(any(t.startswith('Wrong clock on') for t in titles))
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
        p11 = next(p for p in state['switches'][0]['ports'] if p['name'] == '1/1')
        self.assertIsNotNone(p11['rx_bps'])
        with open(os.path.join(self.state_dir, 'events.json')) as fh:
            events = json.load(fh)
        self.assertTrue(any('1/5' in e['message'] and 'down' in e['message'] for e in events))

    def _ap_with_time(self, ts):
        info = aplib.parse_debug_info(fixture('ap_debug_info.xml'))
        info['time'] = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(ts))
        return lambda host, port=8080: dict(info)

    def test_ap_ntp_error_with_good_clock_is_not_a_problem(self):
        with mock.patch.object(collector.aplib, 'read_ap', self._ap_with_time(time.time())):
            state = collector.run(self.cfg)
        self.assertTrue(all(abs(a['clock_skew']) < 5 for a in state['aps']))
        self.assertFalse(any(i['title'].startswith('Wrong clock on') for i in state['insights']))

    def test_switch_time_zone_and_sntp_check(self):
        now = time.time()
        local = time.gmtime(now + 3600)  # switch at UTC+01:00
        self.raw['TimeSetting']['TimeZone'] = {'offsetHour': '+01', 'offsetMinute': '00', 'timeZoneID': 'CET'}
        self.raw['TimeSetting']['setTimeMode'] = '2'
        self.raw['TimeSetting']['CurrentLocalTime'] = {
            'year': str(local.tm_year), 'month': '%02d' % local.tm_mon, 'day': '%02d' % local.tm_mday,
            'hour': '%02d' % local.tm_hour, 'minute': '%02d' % local.tm_min, 'second': '%02d' % local.tm_sec}
        self.raw['SNTPServerTable'] = {'SNTPServerEntry': {
            'IPAddress': '192.0.2.1', 'status': '4', 'lastResponse': '01011900 00:00:00',
            'lastRequest': time.strftime('%m%d%Y %H:%M:%S', local)}}
        state = collector.run(self.cfg)
        sw = state['switches'][0]
        self.assertLess(abs(sw['clock_skew']), 5)
        self.assertEqual(sw['timezone'], '+01:00')
        self.assertIsNone(sw['sntp_list'][0]['last_response'])
        titles = [i['title'] for i in state['insights']]
        self.assertNotIn('Switch clock is wrong', titles)
        self.assertIn('Time server 192.0.2.1 does not answer the switch', titles)

    def test_switch_failure_is_reported(self):
        def boom(dev, persistent):
            raise swlib.SwitchError('login failed: invalid username or password')
        with mock.patch.object(collector, 'fetch_switch_raw', boom):
            state = collector.run(self.cfg)
        self.assertFalse(state['sources']['switch:default']['ok'])
        self.assertIn('invalid username', state['sources']['switch:default']['error'])
        self.assertFalse(state['summary']['switch_online'])
        self.assertIn('Switch 192.0.2.2 unreachable', [i['title'] for i in state['insights']])

    def test_device_types_on_clients(self):
        state = collector.run(self.cfg)
        types = {c.get('type') for c in state['clients']}
        self.assertTrue(types - {'unknown'})
        self.assertTrue(all(c.get('type_label') and c.get('type_icon') for c in state['clients']))


SWITCH_B_MAC = '02:00:00:00:0b:0b'


class MultiSwitchTest(unittest.TestCase):
    """Two switches: B hangs on port 1/24 of A; one device of 1/24 really sits on B port 1/3."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_dir = os.path.join(self.tmp.name, 'state')
        conf = os.path.join(self.tmp.name, 'instanton.conf')
        with open(conf, 'w') as fh:
            fh.write('[general]\nenabled=1\n'
                     '[switch:aaaa-1]\nname=Rack\nhost=192.0.2.2\nusername=u\npassword=p\n'
                     '[switch:bbbb-2]\nname=Garage\nhost=192.0.2.3\nusername=u\npassword=p\n'
                     '[switch:cccc-3]\nenabled=0\nhost=192.0.2.4\nusername=u\npassword=p\n'
                     '[aps]\nenabled=1\ndiscover=1\n')
        self.cfg = Config(conf)
        raw_a = json.loads(fixture('switch_raw.json'))
        a_mac = raw_a['SystemGlobalSetting']['MACAddress']
        fdb_a = raw_a['ForwardingTable']['Entry']
        self.moved = next(e['MACAddress'] for e in fdb_a if e['interfaceName'] == '1/24')
        fdb_a.append({'MACAddress': SWITCH_B_MAC, 'VLANID': '1', 'addressType': '3', 'interfaceName': '1/24',
                      'interfaceType': '1'})
        raw_b = json.loads(fixture('switch_raw.json'))
        raw_b['SystemGlobalSetting'].update({'MACAddress': SWITCH_B_MAC, 'systemName': 'garage-sw'})
        raw_b['LLDPMEDNeighborList'] = {}
        raw_b['ForwardingTable'] = {'Entry': [
            {'MACAddress': a_mac, 'VLANID': '1', 'addressType': '3', 'interfaceName': '1/52', 'interfaceType': '1'},
            {'MACAddress': self.moved, 'VLANID': '1', 'addressType': '3', 'interfaceName': '1/3', 'interfaceType': '1'},
        ]}
        self.raws = {'192.0.2.2': raw_a, '192.0.2.3': raw_b}
        self.patches = [
            mock.patch.object(collector, 'STATE_DIR', self.state_dir),
            mock.patch('lib.config.STATE_DIR', self.state_dir),
            mock.patch.object(collector, 'fetch_switch_raw',
                              lambda dev, persistent: json.loads(json.dumps(self.raws[dev.get('host')]))),
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

    def test_config_lists_switches(self):
        self.assertEqual([d.id for d in self.cfg.switches()], ['aaaa-1', 'bbbb-2'])
        self.assertEqual(len(self.cfg.switches(usable_only=False)), 3)
        self.assertEqual(self.cfg.switch('bbbb-2').label, 'Garage')
        self.assertIsNone(self.cfg.switch())  # ambiguous without an id

    def test_link_between_switches_and_client_location(self):
        state = collector.run(self.cfg)
        a, b = state['switches']
        self.assertEqual((a['label'], b['label']), ('Rack', 'Garage'))
        port = next(p for p in a['ports'] if p['name'] == '1/24')
        self.assertEqual((port['role'], port['peer']), ('switch', 'bbbb-2'))
        client = next(c for c in state['clients'] if c['mac'] == self.moved)
        self.assertEqual((client['switch'], client['port'], client['switch_name']), ('bbbb-2', '1/3', 'Garage'))
        self.assertFalse(any(c['mac'] == SWITCH_B_MAC for c in state['clients']))
        self.assertEqual(state['summary']['switches_online'], 2)
        self.assertEqual(state['summary']['ports_total'], 104)

    def test_topology_tree(self):
        from lib import topology
        state = collector.run(self.cfg)
        nodes = {n['id']: n for n in topology.build(state, state['switches'])['nodes']}
        self.assertEqual(nodes['sw:aaaa-1']['parent'], 'fw')
        self.assertEqual(nodes['sw:bbbb-2']['parent'], 'sw:aaaa-1')
        self.assertEqual(nodes['sw:bbbb-2']['link']['port'], '1/24')
        self.assertEqual(nodes['c:' + self.moved]['parent'], 'sw:bbbb-2')
        self.assertTrue(all(n['parent'] in nodes for n in nodes.values() if n['parent']))

    def test_switch_offline_keeps_the_other(self):
        real = collector.fetch_switch_raw

        def flaky(dev, persistent):
            if dev.get('host') == '192.0.2.3':
                raise swlib.SwitchError('timeout')
            return real(dev, persistent)
        with mock.patch.object(collector, 'fetch_switch_raw', flaky):
            state = collector.run(self.cfg)
        self.assertEqual([s['online'] for s in state['switches']], [True, False])
        self.assertIn('Switch Garage unreachable', [i['title'] for i in state['insights']])


class CloudAndTypesTest(unittest.TestCase):
    def test_site_selection(self):
        from lib import cloud
        client = cloud.InstantOnCloud('u', 'p')
        with mock.patch.object(client, 'sites', lambda: [{'id': 'S1', 'name': 'Home'}, {'id': 'S2', 'name': 'Office'}]):
            self.assertEqual([s['id'] for s in client.select_sites([])], ['S1', 'S2'])
            self.assertEqual([s['id'] for s in client.select_sites(['office'])], ['S2'])
            with self.assertRaises(cloud.CloudError):
                client.select_sites(['Shop'])

    def test_network_never_keeps_passphrase(self):
        from lib import cloud
        net = cloud.normalize_network({'networkName': 'Home', 'preSharedKey': 'secret', 'useVlan': True, 'vlanId': 20,
                                       'isAvailableOn5GHzRadioBand': True})
        self.assertNotIn('secret', json.dumps(net))
        self.assertEqual((net['vlan'], net['bands']), (20, ['5 GHz']))

    def test_device_type_guesses(self):
        from lib import devicetype as dt
        self.assertEqual(dt.classify(['Shelly-Washer'])['type'], 'iot')
        self.assertEqual(dt.classify(['Telecamera Garden'], 'Hangzhou Hikvision')['type'], 'camera')
        self.assertEqual(dt.classify(['Citofono'], 'Hangzhou Hikvision')['type'], 'intercom')
        self.assertEqual(dt.classify([''], 'Synology Incorporated')['type'], 'nas')
        self.assertEqual(dt.classify(['00:11:22:33:44:55'], '', ['Brother', 'Printer'])['type'], 'printer')
        self.assertEqual(dt.classify(['Tab-S9'], '')['type'], 'tablet')
        r = dt.classify([], '')
        self.assertEqual((r['type'], r['type_source']), ('unknown', ''))


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.state = {'switch': {'ports': [
            {'name': '1/1', 'description': 'AP', 'enabled': True, 'role': 'ap',
             'poe': {'enabled': True, 'status': 'delivering'}},
            {'name': '1/51', 'description': 'OPNsense', 'enabled': True, 'role': 'uplink', 'poe': None},
        ], 'sntp_list': [{'address': '192.0.2.9'}]}}

    def test_port_vlans(self):
        state = {'switch': {'vlans': [{'id': 1}, {'id': 20}, {'id': 30}, {'id': 40}], 'ports': [
            {'name': '1/5', 'role': 'device', 'untagged': '1', 'tagged': '20,30', 'enabled': True},
            {'name': '1/51', 'role': 'uplink', 'untagged': '1', 'tagged': '20', 'enabled': True}]}}
        changes, summary = actions.plan('vlans', {'port': '1/5', 'untagged': '20', 'tagged': ['30', '40'], 'confirm': True}, state)
        self.assertEqual(changes, [
            ('VLANInterfaceISList', 'delete', {'Entry': {'interfaceName': '1/5', 'generalTaggedVLANs': '20'}}),
            ('VLANInterfaceISList', 'set', {'Entry': {'interfaceName': '1/5', 'generalTaggedVLANs': '40',
                                                      'generalUntaggedVLANs': '20', 'generalPVID': '20'}})])
        self.assertIn('untagged VLAN 20', summary)
        with self.assertRaisesRegex(actions.ActionError, 'leads to the firewall'):
            actions.plan('vlans', {'port': '1/51', 'untagged': '1', 'tagged': [], 'confirm': True}, state)
        with self.assertRaisesRegex(actions.ActionError, 'does not exist'):
            actions.plan('vlans', {'port': '1/5', 'untagged': '99', 'tagged': [], 'confirm': True}, state)
        with self.assertRaisesRegex(actions.ActionError, 'confirm'):
            actions.plan('vlans', {'port': '1/5', 'untagged': '1', 'tagged': ['20'], 'confirm': False}, state)

    def test_vlan_create_rename_delete(self):
        state = {'switch': {'vlans': [{'id': 1, 'name': ''}, {'id': 20, 'name': 'IoT'}, {'id': 30, 'name': 'HOME'},
                                      {'id': 60, 'name': ''}], 'ports': [
            {'name': '1/5', 'role': 'device', 'untagged': '30', 'tagged': '', 'enabled': True},
            {'name': '1/51', 'role': 'uplink', 'untagged': '1', 'tagged': '20,30', 'enabled': True}]}}
        config = {'sections': {'ManagementInterfaceGlobalSetting': {'managementVLAN': '1'}}}
        changes, summary = actions.plan('vlan', {'op': 'add', 'id': '70', 'name': 'Lab'}, state, config)
        self.assertEqual(changes, [('VLANList', 'add', {'VLAN': {'VLANID': '70', 'VLANName': 'Lab'}})])
        with self.assertRaisesRegex(actions.ActionError, 'already exists'):
            actions.plan('vlan', {'op': 'add', 'id': '20'}, state, config)
        with self.assertRaisesRegex(actions.ActionError, '2 to 4094'):
            actions.plan('vlan', {'op': 'add', 'id': '5000'}, state, config)
        with self.assertRaisesRegex(actions.ActionError, 'letters'):
            actions.plan('vlan', {'op': 'add', 'id': '71', 'name': 'a/b'}, state, config)
        changes, _ = actions.plan('vlan', {'op': 'rename', 'id': '20', 'name': 'Things'}, state, config)
        self.assertEqual(changes[0], ('VLANList', 'set', {'VLAN': {'VLANID': '20', 'VLANName': 'Things'}}))
        changes, _ = actions.plan('vlan', {'op': 'delete', 'id': '60'}, state, config)
        self.assertEqual(changes, [('VLANList', 'delete', {'VLAN': {'VLANID': '60'}})])
        with self.assertRaisesRegex(actions.ActionError, 'leads to the firewall'):
            actions.plan('vlan', {'op': 'delete', 'id': '20', 'confirm': True}, state, config)
        with self.assertRaisesRegex(actions.ActionError, 'default VLAN'):
            actions.plan('vlan', {'op': 'delete', 'id': '1', 'confirm': True}, state, config)
        state['switch']['ports'][1]['tagged'] = '20'
        with self.assertRaisesRegex(actions.ActionError, 'confirm'):
            actions.plan('vlan', {'op': 'delete', 'id': '30'}, state, config)
        changes, summary = actions.plan('vlan', {'op': 'delete', 'id': '30', 'confirm': True}, state, config)
        self.assertIn('1/5', summary)

    def test_port_speed(self):
        state = {'switch': {'ports': [{'name': '1/5', 'role': 'device', 'enabled': True, 'auto_neg': True}]}}
        changes, _ = actions.plan('port', {'port': '1/5', 'mode': '100F'}, state)
        self.assertEqual(changes[0][2]['Entry'], {'interfaceName': '1/5', 'autoNegotiationAdminEnabled': '2',
                                                  'speedAdmin': '100', 'duplexAdminMode': '3'})
        with self.assertRaisesRegex(actions.ActionError, 'nothing to change'):
            actions.plan('port', {'port': '1/5', 'mode': 'auto'}, state)

    def test_link_to_other_switch_is_protected(self):
        state = {'switch': {'ports': [{'name': '1/24', 'enabled': True, 'role': 'switch', 'peer': 'bbbb-2',
                                       'poe': {'enabled': True, 'status': 'searching'}}]}}
        for action, params in (('port', {'port': '1/24', 'enabled': False}), ('poe', {'port': '1/24', 'enabled': False}),
                               ('poe_cycle', {'port': '1/24'}), ('cable_test', {'port': '1/24', 'confirm': True})):
            with self.assertRaisesRegex(actions.ActionError, 'another monitored switch'):
                actions.plan(action, params, state)
        self.assertEqual(actions.uplink_ports(state), {'1/24'})

    def test_build_section(self):
        xml = swlib.build_section('Standard802_3List', 'set', {'Entry': {'interfaceName': '1/1',
                                                                         'interfaceDescription': 'a&b', 'x': None}})
        self.assertEqual(xml, '<Standard802_3List action="set"><Entry><interfaceName>1/1</interfaceName>'
                              '<interfaceDescription>a&amp;b</interfaceDescription></Entry></Standard802_3List>')

    def test_port_changes(self):
        changes, summary = actions.plan('port', {'port': '1/1', 'description': 'Office AP', 'enabled': '0'},
                                        self.state)
        self.assertEqual(changes, [('Standard802_3List', 'set', {'Entry': {
            'interfaceName': '1/1', 'interfaceDescription': 'Office AP', 'adminState': '2'}})])
        self.assertIn('disabled', summary)

    def test_uplink_cannot_be_disabled(self):
        with self.assertRaises(actions.ActionError):
            actions.plan('port', {'port': '1/51', 'enabled': False}, self.state)
        actions.plan('port', {'port': '1/51', 'description': 'Firewall'}, self.state)

    def test_rejects_bad_input(self):
        for action, params in (('port', {'port': '1/9', 'description': 'x'}),
                               ('port', {'port': '1/1', 'description': '<script>'}),
                               ('port', {'port': '1/1'}),
                               ('poe', {'port': '1/51', 'enabled': True}),
                               ('system', {'name': 'bad name'}),
                               ('time', {'timezone': '+1'}),
                               ('time', {'timezone': '+01:00', 'timezone_name': 'CET1'}),
                               ('time', {'sntp_server': 'bad host!'}),
                               ('reboot', {})):
            with self.assertRaises(actions.ActionError, msg='%s %s' % (action, params)):
                actions.plan(action, params, self.state)

    def test_time_change(self):
        changes, _ = actions.plan('time', {'sntp_server': '192.0.2.1', 'timezone': '+01:00', 'dst': 'eu'},
                                  self.state)
        sections = [(c[0], c[1]) for c in changes]
        self.assertEqual(sections, [('TimeSetting', 'set'), ('SNTPServerTable', 'delete'),
                                    ('SNTPServerTable', 'set')])
        ts = changes[0][2]
        self.assertEqual(ts['setTimeMode'], '2')
        self.assertEqual(ts['TimeZone'], {'offsetHour': '+01', 'offsetMinute': '00', 'timeZoneID': 'UTC'})
        self.assertEqual(ts['DayLightSaving']['RecurrentPeriod']['endMonth'], '10')

    def test_execute_saves(self):
        client = mock.Mock()
        res = actions.execute(client, 'poe_cycle', {'port': '1/1'}, self.state, save=True)
        client.apply.assert_called_once()
        client.save_config.assert_called_once()
        self.assertTrue(res['saved'])


if __name__ == '__main__':
    unittest.main()


class CloudNetworkTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(HERE, '..', 'src', 'opnsense', 'scripts', 'instanton'))
        import cloudnet
        self.cn = cloudnet
        self.existing = {
            'id': 'n1', 'networkName': 'Casa', 'isEnabled': True, 'preSharedKey': 'secret-pass', 'useVlan': True,
            'vlanId': 30, 'security': 'wpa3', 'type': 'employee', 'health': 'good', 'wirelessClientsCount': 5,
            'qos': {'isBandwidthLimitEnabled': False, 'downloadBandwidthLimitInMbps': 1000},
            'accessPoints': [{'deviceId': 'AA:BB:CC:00:00:01', 'deviceName': 'AP1', 'isBoundToNetwork': True},
                             {'deviceId': 'aa:bb:cc:00:00:02', 'deviceName': 'AP2', 'isBoundToNetwork': True}]}

    def test_validation(self):
        with self.assertRaisesRegex(self.cn.RequestError, '8 to 63'):
            self.cn.clean({'preSharedKey': 'short'})
        with self.assertRaisesRegex(self.cn.RequestError, '1 to 32'):
            self.cn.clean({'networkName': ''})
        with self.assertRaisesRegex(self.cn.RequestError, '4094'):
            self.cn.clean({'vlanId': 5000})
        self.assertEqual(self.cn.clean({'preSharedKey': ''}), {})  # empty keeps the current password

    def test_update_keeps_password_and_binds_aps(self):
        changes = self.cn.clean({'isEnabled': False, 'boundAccessPoints': ['aa:bb:cc:00:00:01'],
                                 'qos': {'isBandwidthLimitEnabled': True, 'downloadBandwidthLimitInMbps': 25}})
        body = {k: v for k, v in self.existing.items() if k not in self.cn.READ_ONLY}
        net = self.cn.apply_changes(body, changes)
        self.assertEqual(net['preSharedKey'], 'secret-pass')
        self.assertFalse(net['isEnabled'])
        self.assertEqual([ap['isBoundToNetwork'] for ap in net['accessPoints']], [True, False])
        self.assertFalse(net['isBroadcastOnAllBoundApsOnAllBands'])
        body = self.cn.put_body(net)
        self.assertEqual(set(body), set(self.cn.PUT_KEYS))
        self.assertEqual(body['qos']['perClientDownloadBandwidthLimitInMbps'], 25)
        self.assertTrue(body['qos']['isDownloadBandwidthLimitEnabled'])
        self.assertEqual(body['activeSchedule'], 'none')
        self.assertEqual(len(body['weekSchedule']['schedulePerWeekdayMap']), 7)
        self.assertNotIn('health', body)
        self.assertNotIn('preSharedKey', self.cn.public(self.existing))

    def test_new_network(self):
        net = self.cn.new_network([self.existing], self.cn.clean(
            {'networkName': 'Test', 'preSharedKey': 'longenough', 'useVlan': True, 'vlanId': 50, 'isSsidHidden': True}))
        self.assertEqual((net['vlanId'], net['isSsidHidden'], net['authentication']), (50, True, 'psk'))
        self.assertEqual(len(net['accessPoints']), 2)
        self.assertTrue(all(ap['isBoundToNetwork'] for ap in net['accessPoints']))
        with self.assertRaisesRegex(self.cn.RequestError, 'password'):
            self.cn.new_network([self.existing], self.cn.clean({'networkName': 'X'}))
