"""
Build the Instant On state snapshot.

One run polls every enabled source, correlates the results and writes:

* ``state.json``   – the latest snapshot served to the GUI and widget
* ``clients.json`` – every MAC address seen, with first/last seen times
* ``events.json``  – changes detected between two runs (port up/down,
                     AP offline, new device, reboots, ...)
"""

import json
import os
import re
import socket
import subprocess
import syslog
import tempfile
import time
from datetime import datetime

from . import ap as aplib
from . import cloud as cloudlib
from . import hostinfo
from . import switch as swlib
from .config import Config, STATE_DIR, state_path

SWITCH_SECTIONS = [
    'SystemGlobalSetting', 'DiagnosticsUnitList', 'TimeSetting', 'SNTPGlobalSetting',
    'Standard802_3List', 'StatisticsList', 'PoEPSEInterfaceList', 'PoEPSEUnitList',
    'ForwardingTable', 'LLDPMEDNeighborList', 'VLANList', 'VLANMembershipInterfaceList',
    'ConnectedUserList', 'UnexpectedRestart', 'InventoryEntitiesTable',
]
LOG_SECTION = 'MemoryLogTable'

SEVERITY = ['emergency', 'alert', 'critical', 'error', 'warning', 'notice', 'info', 'debug']
POE_STATUS = {'1': 'disabled', '2': 'searching', '3': 'delivering', '4': 'fault', '5': 'test',
              '6': 'fault'}
DUPLEX = {'1': 'half', '2': 'full'}
FAN = {'1': 'ok', '2': 'failed', '3': 'failed', '4': 'warning', '5': 'not present'}
PSU = {'1': 'ok', '2': 'failed', '3': 'failed', '4': 'warning', '5': 'not present'}

LOG_TAG = 'instanton'
UPLINK_HINT = re.compile(r'opnsense|pfsense|firewall|router|gateway|uplink|wan', re.I)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def log(level, message):
    syslog.openlog(LOG_TAG, syslog.LOG_PID, syslog.LOG_DAEMON)
    syslog.syslog(level, message)
    if os.environ.get('INSTANTON_DEBUG'):
        print('[%s] %s' % ({syslog.LOG_ERR: 'error', syslog.LOG_WARNING: 'warning'}.get(level, 'info'), message))


def load_json(name, default):
    try:
        with open(state_path(name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(name, data):
    os.makedirs(STATE_DIR, mode=0o750, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE_DIR, prefix='.%s.' % name)
    with os.fdopen(fd, 'w') as fh:
        json.dump(data, fh, separators=(',', ':'), sort_keys=True)
    os.chmod(tmp, 0o640)
    os.replace(tmp, state_path(name))


def as_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def port_sort_key(name):
    return [as_int(p, 0) if p.isdigit() else p for p in re.split(r'(\d+)', name or '')]


def firewall_macs():
    """MAC addresses of the firewall's own interfaces."""
    macs = set()
    try:
        out = subprocess.run(['ifconfig', '-a'], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ''
    for mac in re.findall(r'(?:ether|lladdr|hwaddr)\s+([0-9a-fA-F:]{17})', out):
        macs.add(hostinfo.norm_mac(mac))
    return macs


def parse_switch_time(entry):
    try:
        return datetime(as_int(entry.get('year')), as_int(entry.get('month')), as_int(entry.get('day')),
                        as_int(entry.get('hour')), as_int(entry.get('minute')),
                        as_int(entry.get('second'))).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def parse_log_time(value):
    """Switch log time is 'MMDDYYYY HH:MM:SS'."""
    try:
        return datetime.strptime(value.strip(), '%m%d%Y %H:%M:%S').timestamp()
    except (ValueError, AttributeError):
        return None


def as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


# --------------------------------------------------------------------------
# switch
# --------------------------------------------------------------------------
# Every login/logout writes two lines into the switch's small in-memory log.
# The monitor daemon therefore keeps one session open between polls and only
# logs in again when the switch drops it.
_sessions = {}


def close_sessions():
    for client in list(_sessions.values()):
        client.logout()
    _sessions.clear()


def _switch_fetch(client):
    raw = client.fetch_many(SWITCH_SECTIONS)
    if 'Standard802_3List' not in raw:
        raise swlib.SwitchError('session expired')
    try:
        raw.update(client.fetch(LOG_SECTION))
    except swlib.SwitchError:
        pass
    return raw


def fetch_switch_raw(cfg, persistent):
    host = cfg.get('switch', 'host')
    key = (host, cfg.get('switch', 'username'), cfg.get('switch', 'password'), cfg.flag('switch', 'verify_tls'))
    if not persistent:
        client = swlib.InstantOnSwitch(host, key[1], key[2], verify_tls=key[3])
        with client:
            return _switch_fetch(client)
    for stale in [k for k in _sessions if k != key]:
        _sessions.pop(stale).logout()
    client = _sessions.get(key)
    if client is not None and client.logged_in:
        try:
            return _switch_fetch(client)
        except swlib.SwitchError:
            client.logged_in = False
    client = swlib.InstantOnSwitch(host, key[1], key[2], verify_tls=key[3])
    client.login()
    _sessions[key] = client
    try:
        return _switch_fetch(client)
    except swlib.SwitchError:
        _sessions.pop(key, None)
        client.logout()
        raise


def collect_switch(cfg, previous, persistent=False):
    host = cfg.get('switch', 'host')
    started = time.time()
    raw = fetch_switch_raw(cfg, persistent)
    now = time.time()
    sysinfo = raw.get('SystemGlobalSetting', {}) or {}
    diag = (swlib.section_entries(raw.get('DiagnosticsUnitList')) or [{}])[0]
    poe_unit = (swlib.section_entries(raw.get('PoEPSEUnitList')) or [{}])[0]
    time_setting = raw.get('TimeSetting', {}) or {}
    sntp = raw.get('SNTPGlobalSetting', {}) or {}
    inventory = swlib.section_entries(raw.get('InventoryEntitiesTable'))

    # LLDP neighbours by port
    neighbors = {}
    for n in swlib.section_entries(raw.get('LLDPMEDNeighborList')):
        addrs = [a.get('addr', '') for a in as_list((n.get('MngAddrList') or {}).get('AddrEntry'))
                 if isinstance(a, dict)]
        descr = n.get('systemDescription', '')
        neighbors[n.get('interfaceName')] = {
            'name': n.get('systemName', ''), 'description': descr,
            'mac': hostinfo.norm_mac(n.get('deviceID', '')) if n.get('deviceIDSubtype') == '4' else '',
            'chassis_id': n.get('deviceID', ''), 'port': n.get('portDescription', ''),
            'ip': next((a for a in addrs if a), ''),
            'is_ap': 'access point' in descr.lower(),
            'capabilities': n.get('systemCapabilitiesEnabled', ''),
        }

    stats = {s.get('interfaceName'): s for s in swlib.section_entries(raw.get('StatisticsList'))}
    poe = {p.get('interfaceName'): p for p in swlib.section_entries(raw.get('PoEPSEInterfaceList'))}
    vlans_by_port = {v.get('interfaceName'): v for v in swlib.section_entries(raw.get('VLANMembershipInterfaceList'))}

    fdb = []
    for e in swlib.section_entries(raw.get('ForwardingTable')):
        if e.get('interfaceName') in (None, '', 'none'):
            continue
        fdb.append({'mac': hostinfo.norm_mac(e.get('MACAddress', '')), 'vlan': as_int(e.get('VLANID')),
                    'port': e.get('interfaceName'), 'type': 'static' if e.get('addressType') == '2' else 'dynamic'})
    macs_per_port = {}
    for e in fdb:
        macs_per_port[e['port']] = macs_per_port.get(e['port'], 0) + 1

    # flapping: link-down messages per port in the switch log. Bursts where
    # many ports drop within a few seconds (switch reboot, firmware update,
    # PoE budget reset) are switch-wide events and are not counted.
    log_entries = []
    downs = []
    for entry in swlib.section_entries(raw.get(LOG_SECTION)):
        msg = re.sub(r'\s+', ' ', entry.get('message', '')).strip()
        sev = as_int(entry.get('severityType'), 6)
        ts = parse_log_time(entry.get('dateTime', ''))
        log_entries.append({'time': ts, 'time_raw': entry.get('dateTime', ''),
                            'severity': SEVERITY[sev] if 0 <= sev < len(SEVERITY) else str(sev),
                            'message': msg, 'seq': as_int(entry.get('logNo'))})
        m = re.search(r'LINK-W-Down: (\S+)', msg)
        if m and ts:
            downs.append((ts, m.group(1)))
    flaps = {}
    for ts, port_name in downs:
        burst = {p for t, p in downs if abs(t - ts) <= 10}
        if len(burst) < 4:
            flaps[port_name] = flaps.get(port_name, 0) + 1
    log_entries.sort(key=lambda x: (x['time'] or 0, x['seq']), reverse=True)

    prev_ports = {p['name']: p for p in (previous.get('switch') or {}).get('ports', [])}
    prev_time = (previous.get('switch') or {}).get('polled_at') or 0
    elapsed = now - prev_time if prev_time else 0

    ports = []
    for p in swlib.section_entries(raw.get('Standard802_3List')):
        if p.get('interfaceType') != '1':
            continue
        name = p.get('interfaceName')
        st = stats.get(name, {})
        pe = poe.get(name)
        rx = as_int(st.get('receivePacketByteCount'))
        tx = as_int(st.get('transmitPacketByteCount'))
        rx_rate = tx_rate = None
        prev = prev_ports.get(name)
        if prev and elapsed > 0 and rx >= prev.get('rx_bytes', 0) and tx >= prev.get('tx_bytes', 0):
            rx_rate = int((rx - prev['rx_bytes']) * 8 / elapsed)
            tx_rate = int((tx - prev['tx_bytes']) * 8 / elapsed)
        vl = vlans_by_port.get(name, {})
        port = {
            'name': name, 'id': as_int(p.get('interfaceID')), 'description': p.get('interfaceDescription', ''),
            'enabled': p.get('adminState') == '1', 'up': p.get('linkState') == '1',
            'speed': as_int(p.get('speedOper')) if p.get('linkState') == '1' else 0,
            'duplex': DUPLEX.get(p.get('duplexOperMode'), '') if p.get('linkState') == '1' else '',
            'link_since': now - as_int(p.get('linkStateDuration')) if p.get('linkStateDuration') else None,
            'media': 'fiber' if p.get('mediaType') == '2' else 'copper',
            'rx_bytes': rx, 'tx_bytes': tx, 'rx_bps': rx_rate, 'tx_bps': tx_rate,
            'errors': as_int(st.get('packetErrorCount')),
            'broadcast_rx': as_int(st.get('receiveBroadcastPacketCount')),
            'pvid': as_int(vl.get('PVID'), 0),
            'tagged': vl.get('currentTaggedVLANs', ''), 'untagged': vl.get('currentUntaggedVLANs', ''),
            'lag': as_int(p.get('LAGID')),
            'mac_count': macs_per_port.get(name, 0),
            'flaps': flaps.get(name, 0),
            'neighbor': neighbors.get(name),
            'poe': None,
        }
        if pe:
            port['poe'] = {
                'enabled': pe.get('adminEnable') == '1',
                'status': POE_STATUS.get(pe.get('detectionStatus'), pe.get('detectionStatus', '')),
                'power_w': round(as_int(pe.get('outputPower')) / 1000.0, 1),
                'class': pe.get('powerClassification', ''),
                'limit_w': round(as_int(pe.get('powerLimit')) / 1000.0, 1),
                'voltage_v': round(as_int(pe.get('outputVoltage')) / 1000.0, 1),
                'current_ma': as_int(pe.get('outputCurrent')),
                'priority': {'1': 'critical', '2': 'high', '3': 'low'}.get(pe.get('powerPriority'), ''),
                'overloads': as_int(pe.get('overLoadCounter')), 'shorts': as_int(pe.get('shortCounter')),
                'denied': as_int(pe.get('powerDeniedCounter')),
            }
        ports.append(port)
    ports.sort(key=lambda x: port_sort_key(x['name']))

    fans = []
    for i in range(1, 7):
        state = diag.get('fan%dStatus' % i)
        if state and state != '5':
            fans.append({'id': i, 'status': FAN.get(state, state)})
    switch_time = parse_switch_time(time_setting.get('CurrentLocalTime') or {})
    poe_nominal = as_int(poe_unit.get('nominalPower'))
    poe_used = as_int(poe_unit.get('consumptionPower'))
    model = next((i.get('PID', '').strip() for i in inventory if i.get('entityType') == '0'), '')
    modules = [{'port': i.get('entityName'), 'type': i.get('PID', '').strip(), 'description': i.get('description', ''),
                'serial': i.get('serialNumber', '').strip()} for i in inventory if i.get('entityType') == '1']
    return {
        'online': True, 'host': host, 'polled_at': now, 'poll_ms': int((now - started) * 1000),
        'name': sysinfo.get('systemName', ''), 'model': model or sysinfo.get('systemDescription', ''),
        'description': sysinfo.get('systemDescription', ''), 'serial': sysinfo.get('serialNumber', ''),
        'mac': hostinfo.norm_mac(sysinfo.get('MACAddress', '')), 'firmware': sysinfo.get('firmwareVersion', ''),
        'firmware_date': sysinfo.get('firmwareReleasedDate', ''), 'boot_version': sysinfo.get('bootVersion', ''),
        'hardware': sysinfo.get('hardwareVersion', ''), 'location': sysinfo.get('systemLocation', ''),
        'uptime': as_int(sysinfo.get('systemUpTime')) // 100,
        'config_saved': sysinfo.get('isRunningConfigEqualToStartupConfig') == '1',
        'temperature': as_int(diag.get('tempSensorValue'), None),
        'temperature_ok': diag.get('temperatureStatus', '1') == '1',
        'psu': PSU.get(diag.get('mainPSStatus'), ''),
        'psu_redundant': PSU.get(diag.get('redundantPSStatus'), ''),
        'fans': fans,
        'clock': switch_time,
        'clock_skew': int(switch_time - now) if switch_time else None,
        'sntp_server': sntp.get('syncServerIPAddress', ''),
        'sntp_servers': as_int(sntp.get('unicastServerCount')),
        'sntp_unicast': sntp.get('unicastUpdateEnabled') == '1',
        'unexpected_restart': (raw.get('UnexpectedRestart') or {}).get('unexpectedRestartOccured') == '1',
        'poe': {'nominal_w': poe_nominal, 'used_w': poe_used,
                'percent': round(poe_used * 100.0 / poe_nominal, 1) if poe_nominal else 0,
                'threshold': as_int(poe_unit.get('usageThreshold'))},
        'sessions': [{'user': s.get('userName', ''), 'address': s.get('inetAddr', ''),
                      'seconds': as_int(s.get('sessionTime'))}
                     for s in swlib.section_entries(raw.get('ConnectedUserList'))],
        'vlans': [{'id': as_int(v.get('VLANID')), 'name': v.get('VLANName', '')}
                  for v in swlib.section_entries(raw.get('VLANList'))],
        'modules': modules,
        'ports': ports,
        'fdb': fdb,
        'log': log_entries[:cfg.int('switch', 'log_entries')],
    }


# --------------------------------------------------------------------------
# access points
# --------------------------------------------------------------------------
def collect_aps(cfg, switch, hosts):
    targets = {}
    for h in cfg.list('aps', 'hosts'):
        targets[h] = {'source': 'manual'}
    by_mac = {}
    if cfg.flag('aps', 'discover') and switch:
        for port in switch.get('ports', []):
            n = port.get('neighbor')
            if n and n.get('is_ap'):
                ip = n.get('ip') or hosts.get(n.get('mac'), {}).get('ip', '')
                key = ip or n.get('mac')
                targets.setdefault(key, {'source': 'lldp'})
                targets[key].update({'port': port['name'], 'lldp_name': n.get('name'), 'mac': n.get('mac'),
                                     'poe_w': (port.get('poe') or {}).get('power_w'), 'speed': port.get('speed'),
                                     'duplex': port.get('duplex')})
                if n.get('mac'):
                    by_mac[n['mac']] = key
    aps = []
    port = cfg.int('aps', 'port')
    for host, meta in targets.items():
        rec = {'host': host, 'source': meta.get('source'), 'port': meta.get('port', ''),
               'name': meta.get('lldp_name', ''), 'mac': meta.get('mac', ''), 'poe_w': meta.get('poe_w'),
               'speed': meta.get('speed'), 'duplex': meta.get('duplex'), 'online': False, 'error': '',
               'wired': bool(meta.get('port'))}
        if re.match(r'^[\d.]+$|^[\w.-]+$', host) and ':' not in host:
            try:
                info = aplib.read_ap(host, port=port)
                info.pop('raw', None)
                rec.update(info)
                rec['online'] = True
            except aplib.APError as exc:
                rec['error'] = str(exc)
        else:
            rec['error'] = 'no IP address known (enable LLDP management address or add it manually)'
        aps.append(rec)
    # name APs found only manually through the switch MAC table / host data
    swarm_master = next((a for a in aps if a.get('master')), None)
    for a in aps:
        if not a['name']:
            a['name'] = hosts.get(a.get('mac'), {}).get('hostname') or a.get('serial') or a['host']
        if not a['wired'] and a['online']:
            a['uplink'] = 'mesh or not connected to the monitored switch'
    aps.sort(key=lambda a: (not a.get('master', False), a['name'].lower()))
    return aps, (swarm_master or {}).get('swarm_size')


# --------------------------------------------------------------------------
# correlation
# --------------------------------------------------------------------------
def classify_ports(cfg, switch, own_macs):
    """Return {port: role} where role is ap / uplink / device / empty."""
    roles = {}
    manual_uplinks = set(cfg.list('switch', 'uplink_ports'))
    own_ports = {e['port'] for e in switch.get('fdb', []) if e['mac'] in own_macs}
    for p in switch.get('ports', []):
        n = p.get('neighbor') or {}
        if p['name'] in manual_uplinks or p['name'] in own_ports:
            roles[p['name']] = 'uplink'
        elif n.get('is_ap'):
            roles[p['name']] = 'ap'
        elif not n and UPLINK_HINT.search(p.get('description', '')) and p['mac_count'] > 1:
            roles[p['name']] = 'uplink'
        elif n:
            roles[p['name']] = 'switch' if n.get('capabilities', '')[2:3] == '1' else 'device'
        elif p['mac_count']:
            roles[p['name']] = 'device'
        else:
            roles[p['name']] = 'empty'
        p['role'] = roles[p['name']]
    return roles


def build_clients(switch, aps, hosts, cloud, roles, known, now):
    ap_by_port = {a['port']: a for a in aps if a.get('port')}
    # a wired port with a single learned address and a description names that device
    port_label = {p['name']: p['description'] for p in (switch or {}).get('ports', [])
                  if p.get('description') and p.get('mac_count') == 1 and p.get('role') == 'device'}
    infra_macs = {a.get('mac') for a in aps if a.get('mac')}
    cloud_clients = {c['mac']: c for c in (cloud or {}).get('clients', []) if c.get('mac')}
    current = {}
    for e in (switch or {}).get('fdb', []):
        role = roles.get(e['port'], 'device')
        if role == 'uplink' or e['mac'] in infra_macs or e['mac'] == (switch or {}).get('mac'):
            continue
        h = hosts.get(e['mac'], {})
        ap = ap_by_port.get(e['port'])
        rec = {
            'mac': e['mac'], 'vlan': e['vlan'], 'port': e['port'],
            'connection': 'wireless' if role == 'ap' else 'wired',
            'ap': ap['name'] if ap else '', 'ip': h.get('ip', ''), 'hostname': h.get('hostname', ''),
            'description': h.get('description', ''), 'lease': h.get('source', ''),
            'port_label': port_label.get(e['port'], ''),
            'vendor': hostinfo.vendor(e['mac']), 'random_mac': hostinfo.is_random_mac(e['mac']),
            'online': True,
        }
        cc = cloud_clients.get(e['mac'])
        if cc:
            rec.update({'ssid': cc.get('ssid'), 'signal': cc.get('signal'), 'band': cc.get('band'),
                        'ap': cc.get('ap') or rec['ap'], 'health': cc.get('health'),
                        'hostname': rec['hostname'] or cc.get('name', '')})
        current[e['mac']] = rec
    # wireless clients reported only by the cloud (e.g. behind a mesh AP)
    for mac, cc in cloud_clients.items():
        if mac not in current:
            h = hosts.get(mac, {})
            current[mac] = {'mac': mac, 'vlan': None, 'port': '', 'connection': cc.get('type') or 'wireless',
                            'ap': cc.get('ap', ''), 'ip': cc.get('ip') or h.get('ip', ''),
                            'hostname': h.get('hostname') or cc.get('name', ''), 'description': h.get('description', ''),
                            'lease': h.get('source', ''), 'vendor': hostinfo.vendor(mac),
                            'random_mac': hostinfo.is_random_mac(mac), 'online': True, 'ssid': cc.get('ssid'),
                            'signal': cc.get('signal'), 'band': cc.get('band'), 'health': cc.get('health')}
    events = []
    for mac, rec in current.items():
        k = known.get(mac)
        if not k:
            known[mac] = k = {'first_seen': now}
            events.append(('info', 'client', 'New device %s%s on %s' % (
                mac, ' (%s)' % (rec['hostname'] or rec['vendor']) if (rec['hostname'] or rec['vendor']) else '',
                rec['ap'] and 'AP %s' % rec['ap'] or 'port %s' % rec['port'])))
        elif k.get('port') and rec['port'] and k['port'] != rec['port'] and rec['connection'] == 'wireless' \
                and k.get('connection') == 'wireless':
            rec['roamed_from'] = k.get('ap') or k['port']
        k.update({'last_seen': now, 'port': rec['port'], 'ap': rec['ap'], 'connection': rec['connection'],
                  'ip': rec['ip'] or k.get('ip', ''), 'hostname': rec['hostname'] or k.get('hostname', ''),
                  'vlan': rec['vlan'], 'vendor': rec['vendor'],
                  'port_label': rec.get('port_label') or k.get('port_label', '')})
        rec['first_seen'] = k['first_seen']
        rec['last_seen'] = now
    offline = []
    for mac, k in known.items():
        if mac not in current:
            offline.append({'mac': mac, 'vlan': k.get('vlan'), 'port': k.get('port', ''),
                            'connection': k.get('connection', ''), 'ap': k.get('ap', ''),
                            'ip': hosts.get(mac, {}).get('ip') or k.get('ip', ''),
                            'hostname': hosts.get(mac, {}).get('hostname') or k.get('hostname', ''),
                            'description': hosts.get(mac, {}).get('description', ''), 'lease': '',
                            'vendor': k.get('vendor', ''), 'random_mac': hostinfo.is_random_mac(mac),
                            'port_label': k.get('port_label', ''), 'online': False, 'first_seen': k.get('first_seen'), 'last_seen': k.get('last_seen')})
    clients = sorted(current.values(), key=lambda c: (c['connection'], c['ap'], port_sort_key(c['port']), c['mac']))
    offline.sort(key=lambda c: -(c.get('last_seen') or 0))
    return clients + offline, events


# --------------------------------------------------------------------------
# health checks
# --------------------------------------------------------------------------
def insights(cfg, switch, aps, clients):
    out = []

    def add(level, area, title, detail):
        out.append({'level': level, 'area': area, 'title': title, 'detail': detail})

    if switch and switch.get('online'):
        skew = switch.get('clock_skew')
        if skew is not None and abs(skew) > cfg.int('general', 'clock_skew_seconds'):
            add('warning', 'switch', 'Switch clock is wrong',
                'The switch clock differs from the firewall by %s. Log timestamps are unreliable. '
                'Configure an SNTP server (e.g. the firewall) on the switch.' % human_duration(abs(skew)))
        if not switch.get('sntp_servers'):
            add('warning', 'switch', 'No time server configured on the switch',
                'SNTP has no unicast server. Point it to the firewall so logs and events line up.')
        if not switch.get('config_saved'):
            add('warning', 'switch', 'Running configuration not saved',
                'The switch has unsaved changes that will be lost on reboot.')
        if switch.get('unexpected_restart'):
            add('warning', 'switch', 'Unexpected switch restart', 'The switch reports an unexpected restart.')
        if not switch.get('temperature_ok'):
            add('critical', 'switch', 'Switch temperature alarm', 'Sensor reads %s °C.' % switch.get('temperature'))
        for fan in switch.get('fans', []):
            if fan['status'] != 'ok':
                add('critical', 'switch', 'Fan %d %s' % (fan['id'], fan['status']), 'Check the switch ventilation.')
        if switch.get('psu') not in ('', 'ok'):
            add('critical', 'switch', 'Power supply %s' % switch['psu'], 'Main power supply reports a problem.')
        poe = switch.get('poe') or {}
        if poe.get('percent', 0) >= cfg.int('general', 'poe_warn_percent'):
            add('warning', 'poe', 'PoE budget at %s%%' % poe['percent'],
                '%s W used of %s W.' % (poe.get('used_w'), poe.get('nominal_w')))
        flap_limit = cfg.int('general', 'flap_threshold')
        flapping = [p for p in switch.get('ports', []) if p.get('flaps', 0) >= flap_limit]
        if flapping:
            add('warning', 'ports', 'Ports going up and down',
                ', '.join('%s%s (%d times)' % (p['name'], ' "%s"' % p['description'] if p['description'] else '',
                                               p['flaps'])
                          for p in sorted(flapping, key=lambda x: -x['flaps'])[:10]) +
                '. Counted from link-down messages in the switch log; check cables and connected devices.')
        for p in switch.get('ports', []):
            if p.get('up') and p.get('errors'):
                add('warning', 'ports', 'Errors on port %s' % p['name'],
                    '%d packet errors since the counters were cleared.' % p['errors'])
            if p.get('up') and p.get('duplex') == 'half':
                add('warning', 'ports', 'Half duplex on port %s' % p['name'], 'Possible auto-negotiation problem.')
            if p.get('role') == 'ap' and p.get('up') and p.get('speed') and p['speed'] < 1000:
                add('warning', 'ports', 'Access point on port %s linked at %d Mb/s' % (p['name'], p['speed']),
                    'Access points should link at 1 Gb/s or more; check the cable.')
            pe = p.get('poe') or {}
            if pe.get('status') == 'fault' or pe.get('shorts') or pe.get('overloads'):
                add('warning', 'poe', 'PoE problem on port %s' % p['name'],
                    'status %s, overloads %s, shorts %s' % (pe.get('status'), pe.get('overloads'), pe.get('shorts')))
    for a in aps:
        if not a.get('online'):
            add('critical', 'aps', 'Access point %s unreachable' % a['name'], a.get('error', ''))
            continue
        if a.get('crashed'):
            add('warning', 'aps', '%s restarted after a crash' % a['name'], a.get('reboot_cause', ''))
        if a.get('cloud_status') and a['cloud_status'].upper() != 'CONNECTED':
            add('info', 'aps', '%s not connected to the cloud' % a['name'], a.get('cloud_reason') or a['cloud_status'])
        if not a.get('wired'):
            add('info', 'aps', '%s has no wired link on the monitored switch' % a['name'],
                'It is meshed or connected elsewhere; its wireless clients appear behind its uplink AP.')
    ntp_fail = [a for a in aps if a.get('online') and a.get('ntp_status', '').upper() == 'ERROR']
    if ntp_fail:
        servers = sorted({a.get('ntp_server') or '?' for a in ntp_fail})
        add('warning', 'aps', 'Time sync failing on %d access point%s' % (len(ntp_fail), 's' if len(ntp_fail) > 1 else ''),
            '%s cannot reach NTP server %s. Make sure the NTP service (Services > Network Time) listens on '
            'that interface and the firewall rules allow UDP 123 from the access points.'
            % (', '.join(a['name'] for a in ntp_fail), ', '.join(servers)))
    firmwares = {a.get('firmware') for a in aps if a.get('firmware')}
    if len(firmwares) > 1:
        add('info', 'aps', 'Access points run different firmware', ', '.join(sorted(firmwares)))
    unknown = [c for c in clients if c.get('online') and not c.get('ip') and not c.get('hostname')
               and not c.get('port_label')]
    if unknown:
        add('info', 'clients', '%d devices without IP or name' % len(unknown),
            'Seen on the switch but not in the firewall ARP table or DHCP leases (other VLAN, static IP, '
            'or silent device).')
    order = {'critical': 0, 'warning': 1, 'info': 2}
    out.sort(key=lambda x: order.get(x['level'], 3))
    return out


def human_duration(seconds):
    seconds = int(seconds)
    if seconds >= 86400:
        return '%dd %dh' % (seconds // 86400, (seconds % 86400) // 3600)
    if seconds >= 3600:
        return '%dh %dm' % (seconds // 3600, (seconds % 3600) // 60)
    if seconds >= 60:
        return '%dm %ds' % (seconds // 60, seconds % 60)
    return '%ds' % seconds


# --------------------------------------------------------------------------
# change detection
# --------------------------------------------------------------------------
def diff_events(previous, state):
    ev = []
    psw, sw = previous.get('switch') or {}, state.get('switch') or {}
    if psw.get('online') and sw.get('online'):
        if sw.get('uptime', 0) + 120 < psw.get('uptime', 0):
            ev.append(('warning', 'switch', 'Switch restarted (uptime %s)' % human_duration(sw['uptime'])))
        pports = {p['name']: p for p in psw.get('ports', [])}
        for p in sw.get('ports', []):
            old = pports.get(p['name'])
            if not old:
                continue
            label = p['name'] + (' "%s"' % p['description'] if p['description'] else '')
            if old['up'] and not p['up']:
                ev.append(('warning' if p.get('role') in ('ap', 'uplink') else 'info', 'port', 'Port %s down' % label))
            elif not old['up'] and p['up']:
                ev.append(('info', 'port', 'Port %s up at %s Mb/s %s duplex' % (label, p['speed'], p['duplex'])))
            op, np_ = (old.get('poe') or {}).get('status'), (p.get('poe') or {}).get('status')
            if op and np_ and op != np_ and 'fault' in (op, np_):
                ev.append(('warning', 'poe', 'PoE on port %s: %s -> %s' % (label, op, np_)))
        if psw.get('temperature_ok', True) and not sw.get('temperature_ok', True):
            ev.append(('error', 'switch', 'Switch temperature alarm (%s C)' % sw.get('temperature')))
    pa = {a['host']: a for a in previous.get('aps', [])}
    for a in state.get('aps', []):
        old = pa.get(a['host'])
        if not old:
            continue
        if old.get('online') and not a.get('online'):
            ev.append(('error', 'ap', 'Access point %s went offline: %s' % (a['name'], a.get('error', ''))))
        elif not old.get('online') and a.get('online'):
            ev.append(('info', 'ap', 'Access point %s back online' % a['name']))
        if a.get('online') and old.get('online'):
            if old.get('reboot_cause') != a.get('reboot_cause') and a.get('reboot_cause'):
                ev.append(('warning', 'ap', 'Access point %s restarted: %s' % (a['name'], a['reboot_cause'])))
            if old.get('firmware') != a.get('firmware'):
                ev.append(('info', 'ap', 'Access point %s firmware %s -> %s' % (a['name'], old.get('firmware'),
                                                                                a.get('firmware'))))
            if old.get('cloud_status') != a.get('cloud_status'):
                ev.append(('info', 'ap', 'Access point %s cloud status: %s' % (a['name'], a.get('cloud_status'))))
            if old.get('master') != a.get('master') and a.get('master'):
                ev.append(('info', 'ap', 'Access point %s is now the swarm coordinator' % a['name']))
    for src in ('switch', 'cloud'):
        was, now = (previous.get('sources') or {}).get(src, {}), (state.get('sources') or {}).get(src, {})
        if was.get('ok') and now.get('enabled') and not now.get('ok'):
            ev.append(('error', src, '%s polling failed: %s' % (src.capitalize(), now.get('error'))))
        elif was.get('enabled') and not was.get('ok') and now.get('ok'):
            ev.append(('info', src, '%s polling recovered' % src.capitalize()))
    return ev


# --------------------------------------------------------------------------
# main entry
# --------------------------------------------------------------------------
def run(cfg=None, persistent=False):
    cfg = cfg or Config()
    now = time.time()
    previous = load_json('state.json', {})
    known = load_json('clients.json', {})
    events = load_json('events.json', [])
    state = {'generated': now, 'hostname': socket.gethostname(), 'sources': {}, 'version': 1}
    started = time.time()

    hosts = hostinfo.collect()
    state['sources']['host'] = {'enabled': True, 'ok': True, 'detail': ', '.join(hostinfo.available_sources()),
                                'entries': len(hosts)}

    switch = None
    if cfg.flag('switch', 'enabled') and cfg.get('switch', 'host'):
        try:
            switch = collect_switch(cfg, previous, persistent)
            state['sources']['switch'] = {'enabled': True, 'ok': True, 'ms': switch['poll_ms']}
        except (swlib.SwitchError, OSError, ValueError) as exc:
            state['sources']['switch'] = {'enabled': True, 'ok': False, 'error': str(exc)}
            log(syslog.LOG_ERR, 'switch %s: %s' % (cfg.get('switch', 'host'), exc))
            switch = {'online': False, 'host': cfg.get('switch', 'host'), 'error': str(exc), 'ports': [], 'fdb': []}
    else:
        state['sources']['switch'] = {'enabled': False, 'ok': False}
    state['switch'] = switch

    roles = classify_ports(cfg, switch, firewall_macs()) if switch and switch.get('online') else {}

    aps = []
    if cfg.flag('aps', 'enabled'):
        aps, swarm = collect_aps(cfg, switch if switch and switch.get('online') else None, hosts)
        state['swarm_size'] = swarm
        state['sources']['aps'] = {'enabled': True, 'ok': all(a['online'] for a in aps) if aps else True,
                                   'entries': len(aps), 'online': sum(1 for a in aps if a['online'])}
    else:
        state['sources']['aps'] = {'enabled': False, 'ok': False}
    state['aps'] = aps

    cloud = None
    if cfg.flag('cloud', 'enabled') and cfg.get('cloud', 'username'):
        try:
            cloud = cloudlib.InstantOnCloud(cfg.get('cloud', 'username'), cfg.get('cloud', 'password'),
                                            cfg.get('cloud', 'site') or None).collect()
            state['sources']['cloud'] = {'enabled': True, 'ok': True, 'site': cloud['site'].get('name')}
        except (cloudlib.CloudError, OSError, ValueError, KeyError) as exc:
            state['sources']['cloud'] = {'enabled': True, 'ok': False, 'error': str(exc)}
            log(syslog.LOG_ERR, 'cloud: %s' % exc)
    else:
        state['sources']['cloud'] = {'enabled': False, 'ok': False}
    state['cloud'] = cloud

    clients, client_events = build_clients(switch if switch and switch.get('online') else None, aps, hosts,
                                           cloud, roles, known, now)
    # prune clients not seen within the retention period
    keep = now - cfg.int('general', 'history_days') * 86400
    known = {m: k for m, k in known.items() if (k.get('last_seen') or now) >= keep}
    clients = [c for c in clients if c['online'] or c['mac'] in known]
    state['clients'] = clients
    per_ap = {}
    for c in clients:
        if c['online'] and c['connection'] == 'wireless' and c.get('ap'):
            per_ap[c['ap']] = per_ap.get(c['ap'], 0) + 1
    for a in aps:
        a['clients'] = per_ap.get(a['name'], 0)
    state['insights'] = insights(cfg, switch, aps, clients)
    online = [c for c in clients if c['online']]
    state['summary'] = {
        'switch_online': bool(switch and switch.get('online')),
        'ports_up': sum(1 for p in (switch or {}).get('ports', []) if p['up']),
        'ports_total': len((switch or {}).get('ports', [])),
        'poe_w': ((switch or {}).get('poe') or {}).get('used_w'),
        'poe_percent': ((switch or {}).get('poe') or {}).get('percent'),
        'aps_online': sum(1 for a in aps if a['online']), 'aps_total': len(aps),
        'clients_online': len(online),
        'clients_wireless': sum(1 for c in online if c['connection'] == 'wireless'),
        'clients_wired': sum(1 for c in online if c['connection'] == 'wired'),
        'warnings': sum(1 for i in state['insights'] if i['level'] in ('warning', 'critical')),
    }
    state['duration_ms'] = int((time.time() - started) * 1000)

    new_events = diff_events(previous, state) if previous else []
    if previous:  # no "new device" flood on the very first run
        new_events += client_events
    for level, area, message in new_events:
        events.append({'time': now, 'level': level, 'area': area, 'message': message})
        log({'error': syslog.LOG_ERR, 'warning': syslog.LOG_WARNING}.get(level, syslog.LOG_NOTICE),
            '[%s] %s' % (area, message))
    limit = cfg.int('general', 'event_limit')
    events = [e for e in events if e['time'] >= keep][-limit:]

    save_json('state.json', state)
    save_json('clients.json', known)
    save_json('events.json', events)
    log(syslog.LOG_INFO, 'poll done in %d ms: switch=%s aps=%d/%d clients=%d events=%d' % (
        state['duration_ms'], 'ok' if state['summary']['switch_online'] else 'down',
        state['summary']['aps_online'], state['summary']['aps_total'], len(online), len(new_events)))
    return state
