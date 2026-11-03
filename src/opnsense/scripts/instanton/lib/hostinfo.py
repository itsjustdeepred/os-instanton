"""
Host-side data from the firewall itself: ARP/NDP table, DHCP leases
(ISC dhcpd, Kea, Dnsmasq) and static mappings from config.xml.

Every source is optional: missing files or tools are skipped silently so
the collector works on any OPNsense setup (and on a development machine).
"""

import csv
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

CONFIG_XML = '/conf/config.xml'
ISC_LEASES = '/var/dhcpd/var/db/dhcpd.leases'
KEA_LEASES = '/var/db/kea/kea-leases4.csv'
DNSMASQ_LEASES = '/var/db/dnsmasq.leases'

MAC_RE = re.compile(r'([0-9a-fA-F]{1,2}(?::[0-9a-fA-F]{1,2}){5})')


def norm_mac(mac):
    if not mac:
        return ''
    parts = re.split(r'[:\-.]', mac.strip().lower())
    if len(parts) == 3 and all(len(p) == 4 for p in parts):
        joined = ''.join(parts)
        parts = [joined[i:i + 2] for i in range(0, 12, 2)]
    if len(parts) != 6:
        return mac.strip().lower()
    return ':'.join(p.zfill(2) for p in parts)


def is_random_mac(mac):
    """Locally administered unicast address (privacy / randomized MAC)."""
    try:
        return bool(int(norm_mac(mac).split(':')[0], 16) & 0x02)
    except (ValueError, IndexError):
        return False


_vendor_cache = {}


def vendor(mac):
    mac = norm_mac(mac)
    if not mac:
        return ''
    if is_random_mac(mac):
        return 'Private (randomized MAC)'
    prefix = mac[:8]
    if prefix in _vendor_cache:
        return _vendor_cache[prefix]
    name = ''
    try:
        from netaddr import EUI  # shipped with OPNsense
        name = EUI(mac).oui.registration().org
    except Exception:
        name = ''
    _vendor_cache[prefix] = name
    return name


def arp_table():
    """mac -> {ip, interface} from `arp -an` (FreeBSD and Linux formats)."""
    out = {}
    try:
        text = subprocess.run(['arp', '-an'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        text = ''
    for line in text.splitlines():
        ip = re.search(r'\(([\d.]+)\)', line)
        mac = MAC_RE.search(line.split(' at ', 1)[-1]) if ' at ' in line else None
        if not ip or not mac:
            continue
        iface = re.search(r' on (\S+)', line)
        out[norm_mac(mac.group(1))] = {'ip': ip.group(1), 'interface': iface.group(1) if iface else ''}
    return out


def isc_leases(path=ISC_LEASES):
    out = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return out
    for ip, body in re.findall(r'lease ([\d.]+) \{(.*?)\}', text, re.S):
        mac = re.search(r'hardware ethernet ([0-9a-f:]+);', body)
        if not mac:
            continue
        state = re.search(r'binding state (\w+);', body)
        if state and state.group(1) != 'active':
            continue
        host = re.search(r'client-hostname "([^"]*)";', body)
        out[norm_mac(mac.group(1))] = {'ip': ip, 'hostname': host.group(1) if host else '', 'source': 'dhcp'}
    return out


def kea_leases(path=KEA_LEASES):
    out = {}
    try:
        fh = open(path, encoding='utf-8', errors='replace')
    except OSError:
        return out
    now = time.time()
    with fh:
        for row in csv.DictReader(fh):
            try:
                if int(row.get('expire') or 0) < now or row.get('state', '0') != '0':
                    continue
            except ValueError:
                pass
            mac = norm_mac(row.get('hwaddr', ''))
            if mac:
                out[mac] = {'ip': row.get('address', ''), 'hostname': (row.get('hostname') or '').rstrip('.'),
                            'source': 'dhcp'}
    return out


def dnsmasq_leases(path=DNSMASQ_LEASES):
    out = {}
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            lines = fh.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and MAC_RE.fullmatch(parts[1] or ''):
            out[norm_mac(parts[1])] = {'ip': parts[2], 'hostname': '' if parts[3] == '*' else parts[3],
                                      'source': 'dhcp'}
    return out


def static_mappings(path=CONFIG_XML):
    """Static DHCP reservations (ISC, Kea, Dnsmasq) with names and descriptions."""
    out = {}
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return out

    def add(mac, ip, host, descr):
        mac = norm_mac(mac or '')
        if mac:
            out[mac] = {'ip': (ip or '').strip(), 'hostname': (host or '').strip(),
                        'description': (descr or '').strip(), 'source': 'static'}

    for sm in root.findall('./dhcpd/*/staticmap'):
        add(sm.findtext('mac'), sm.findtext('ipaddr'), sm.findtext('hostname'), sm.findtext('descr'))
    for res in root.iter('reservation'):
        add(res.findtext('hw_address'), res.findtext('ip_address'), res.findtext('hostname'),
            res.findtext('description'))
    for host in root.findall('./dnsmasq/hosts'):
        add(host.findtext('hwaddr'), host.findtext('ip'), host.findtext('host'), host.findtext('descr'))
    return out


def collect():
    """mac -> merged host record (static > dhcp > arp)."""
    hosts = {}
    for mac, rec in arp_table().items():
        hosts[mac] = {'ip': rec['ip'], 'hostname': '', 'description': '', 'source': 'arp',
                      'interface': rec['interface']}
    for source in (isc_leases(), kea_leases(), dnsmasq_leases(), static_mappings()):
        for mac, rec in source.items():
            cur = hosts.setdefault(mac, {'ip': '', 'hostname': '', 'description': '', 'source': '',
                                         'interface': ''})
            for key in ('ip', 'hostname', 'description'):
                if rec.get(key):
                    cur[key] = rec[key]
            cur['source'] = rec['source'] if rec['source'] == 'static' or not cur['source'] else cur['source']
    return hosts


def available_sources():
    found = []
    if os.path.exists(ISC_LEASES):
        found.append('isc-dhcpd')
    if os.path.exists(KEA_LEASES):
        found.append('kea')
    if os.path.exists(DNSMASQ_LEASES):
        found.append('dnsmasq')
    if os.path.exists(CONFIG_XML):
        found.append('static-mappings')
    return found
