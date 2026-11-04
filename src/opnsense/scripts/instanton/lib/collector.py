"""
Build the Instant On state snapshot.

One run polls every enabled source, correlates the results and writes:

* ``state.json``   – the latest snapshot served to the GUI and widget
* ``clients.json`` – every MAC address seen, with first/last seen times
* ``events.json``  – changes detected between two runs (port up/down,
                     AP offline, new device, reboots, ...)
"""

import calendar
import json
import os
import re
import socket
import subprocess
import syslog
import tempfile
import time
from datetime import datetime

from . import actions
from . import ap as aplib
from . import cloud as cloudlib
from . import devicetype
from . import hostinfo
from . import switch as swlib
from .config import Config, STATE_DIR, state_path

SWITCH_SECTIONS = [
    'SystemGlobalSetting', 'DiagnosticsUnitList', 'TimeSetting', 'SNTPGlobalSetting', 'SNTPServerTable',
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


def parse_switch_time(entry, offset=0):
    """Switch clock (local time of the switch) -> epoch, given its UTC offset in seconds."""
    try:
        return calendar.timegm(datetime(
            as_int(entry.get('year')), as_int(entry.get('month')), as_int(entry.get('day')),
            as_int(entry.get('hour')), as_int(entry.get('minute')), as_int(entry.get('second'))).timetuple()) - offset
    except (ValueError, TypeError, AttributeError):
        return None


def parse_log_time(value, offset=0):
    """Switch log time is 'MMDDYYYY HH:MM:SS' in the switch's local time."""
    try:
        return calendar.timegm(datetime.strptime(value.strip(), '%m%d%Y %H:%M:%S').timetuple()) - offset
    except (ValueError, AttributeError):
        return None


def tz_offset(time_setting):
    """Configured time zone of the switch in seconds east of UTC."""
    tz = time_setting.get('TimeZone') or {}
    raw = str(tz.get('offsetHour') or '0').strip()
    sign = -1 if raw.startswith('-') else 1
    return sign * (as_int(raw.lstrip('+-')) * 3600 + as_int(tz.get('offsetMinute')) * 60)


def dst_rule(time_setting):
    """Daylight saving rule: off, eu, us or custom."""
    if time_setting.get('dayLightSavingMode') not in ('1', '2'):
        return 'off'
    rec = (time_setting.get('DayLightSaving') or {}).get('RecurrentPeriod') or {}
    for name, preset in actions.DST_PRESETS.items():
        if preset and all(as_int(rec.get(k), -1) == as_int(v) for k, v in preset.items()):
            return name
    return 'custom'


def switch_utc_offset(time_setting, now):
    """UTC offset (seconds) of the switch clock: time zone, plus one hour when
    daylight saving is configured and that matches the clock better."""
    offset = tz_offset(time_setting)
    candidates = [offset]
    if time_setting.get('dayLightSavingMode') in ('1', '2'):
        candidates.append(offset + 3600)
    naive = parse_switch_time(time_setting.get('CurrentLocalTime') or {}, 0)
    if naive is None:
        return offset
    return min(candidates, key=lambda o: abs(naive - o - now))


def format_offset(seconds):
    sign = '-' if seconds < 0 else '+'
    seconds = abs(seconds)
    return '%s%02d:%02d' % (sign, seconds // 3600, seconds % 3600 // 60)


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


def session_key(dev):
    return (dev.get('host'), dev.get('username'), dev.get('password'), dev.flag('verify_tls'))


def drop_stale_sessions(devices):
    """Log out of switches that were removed from the settings or changed credentials."""
    keep = {session_key(d) for d in devices}
    for stale in [k for k in _sessions if k not in keep]:
        _sessions.pop(stale).logout()


def fetch_switch_raw(dev, persistent):
    key = session_key(dev)
    host = key[0]
    if not persistent:
        client = swlib.InstantOnSwitch(host, key[1], key[2], verify_tls=key[3])
        with client:
            return _switch_fetch(client)
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


def collect_switch(cfg, dev, previous_switch, persistent=False):
    host = dev.get('host')
    started = time.time()
    raw = fetch_switch_raw(dev, persistent)
    now = time.time()
    sysinfo = raw.get('SystemGlobalSetting', {}) or {}
    diag = (swlib.section_entries(raw.get('DiagnosticsUnitList')) or [{}])[0]
    poe_unit = (swlib.section_entries(raw.get('PoEPSEUnitList')) or [{}])[0]
    time_setting = raw.get('TimeSetting', {}) or {}
    sntp = raw.get('SNTPGlobalSetting', {}) or {}
    utc_offset = switch_utc_offset(time_setting, time.time())
    sntp_list = []
    for s in swlib.section_entries(raw.get('SNTPServerTable')):
        last_ok = parse_log_time(s.get('lastResponse', ''), utc_offset)
        sntp_list.append({'address': s.get('IPAddress', ''), 'stratum': s.get('stratum', ''),
                          'last_response': last_ok if last_ok and last_ok > 946684800 else None,
                          'last_request': parse_log_time(s.get('lastRequest', ''), utc_offset),
                          'status': s.get('status', '')})
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
        ts = parse_log_time(entry.get('dateTime', ''), utc_offset)
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

    prev_ports = {p['name']: p for p in (previous_switch or {}).get('ports', [])}
    prev_time = (previous_switch or {}).get('polled_at') or 0
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
            'auto_neg': p.get('autoNegotiationAdminEnabled', '1') == '1',
            'speed_admin': as_int(p.get('speedAdmin')),
            'duplex_admin': 'half' if p.get('duplexAdminMode') == '2' else 'full',
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
    switch_time = parse_switch_time(time_setting.get('CurrentLocalTime') or {}, utc_offset)
    poe_nominal = as_int(poe_unit.get('nominalPower'))
    poe_used = as_int(poe_unit.get('consumptionPower'))
    model = next((i.get('PID', '').strip() for i in inventory if i.get('entityType') == '0'), '')
    modules = [{'port': i.get('entityName'), 'type': i.get('PID', '').strip(), 'description': i.get('description', ''),
                'serial': i.get('serialNumber', '').strip()} for i in inventory if i.get('entityType') == '1']
    return {
        'id': dev.id, 'label': dev.get('name') or sysinfo.get('systemName', '') or host,
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
        'sntp_list': sntp_list,
        'time_mode': 'sntp' if time_setting.get('setTimeMode') == '2' else 'manual',
        'timezone': format_offset(tz_offset(time_setting)),
        'timezone_name': ((time_setting.get('TimeZone') or {}).get('timeZoneID') or '').strip(),
        'dst': dst_rule(time_setting),
        'contact': sysinfo.get('systemContact', ''),
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
        'log': log_entries[:cfg.int('general', 'log_entries')],
    }


# --------------------------------------------------------------------------
# access points
# --------------------------------------------------------------------------
def collect_aps(cfg, switches, hosts):
    targets = {}
    for h in cfg.list('aps', 'hosts'):
        targets[h] = {'source': 'manual'}
    if cfg.flag('aps', 'discover'):
        for sw in switches:
            for port in sw.get('ports', []):
                n = port.get('neighbor')
                if n and n.get('is_ap'):
                    ip = n.get('ip') or hosts.get(n.get('mac'), {}).get('ip', '')
                    key = ip or n.get('mac')
                    targets.setdefault(key, {'source': 'lldp'})
                    targets[key].update({'port': port['name'], 'switch': sw['id'], 'switch_name': sw.get('label', ''),
                                         'lldp_name': n.get('name'), 'mac': n.get('mac'),
                                         'poe_w': (port.get('poe') or {}).get('power_w'), 'speed': port.get('speed'),
                                         'duplex': port.get('duplex')})
    aps = []
    port = cfg.int('aps', 'port')
    for host, meta in targets.items():
        rec = {'host': host, 'source': meta.get('source'), 'port': meta.get('port', ''),
               'switch': meta.get('switch', ''), 'switch_name': meta.get('switch_name', ''),
               'name': meta.get('lldp_name', ''), 'mac': meta.get('mac', ''), 'poe_w': meta.get('poe_w'),
               'speed': meta.get('speed'), 'duplex': meta.get('duplex'), 'online': False, 'error': '',
               'wired': bool(meta.get('port'))}
        if re.match(r'^[\d.]+$|^[\w.-]+$', host) and ':' not in host:
            try:
                info = aplib.read_ap(host, port=port)
                info.pop('raw', None)
                rec.update(info)
                rec['online'] = True
                try:  # the access point clock runs in UTC
                    rec['clock_skew'] = int(calendar.timegm(time.strptime(info.get('time', ''), '%Y-%m-%d %H:%M:%S'))
                                            - time.time())
                except ValueError:
                    rec['clock_skew'] = None
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
def classify_ports(dev, switch, own_macs, switch_macs=()):
    """Set p['role'] on every port and return {port: role}.

    Roles: uplink (towards the firewall), ap, switch (another switch, monitored
    or not), device, empty. ``switch_macs`` maps the MAC addresses of the other
    monitored switches to their id, so links between them are recognised even
    without LLDP.
    """
    roles = {}
    manual_uplinks = set(dev.list('uplink_ports')) if dev else set()
    own_ports = {e['port'] for e in switch.get('fdb', []) if e['mac'] in own_macs}
    peer_ports = {}
    for e in switch.get('fdb', []):
        if e['mac'] in switch_macs and switch_macs[e['mac']] != switch.get('id'):
            peer_ports.setdefault(e['port'], switch_macs[e['mac']])
    for p in switch.get('ports', []):
        n = p.get('neighbor') or {}
        peer = switch_macs.get(n.get('mac')) if n.get('mac') else None
        if peer == switch.get('id'):
            peer = None
        p['peer'] = peer or (peer_ports.get(p['name']) if p['name'] not in own_ports else None) or ''
        if p['name'] in manual_uplinks or p['name'] in own_ports:
            roles[p['name']] = 'uplink'
        elif n.get('is_ap'):
            roles[p['name']] = 'ap'
        elif p['peer']:
            roles[p['name']] = 'switch'
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


def type_info(kind):
    kind = kind if kind in devicetype.TYPES else 'unknown'
    return (kind,) + devicetype.TYPES[kind]


def build_clients(switches, aps, hosts, cloud, known, now):
    """Correlate the MAC tables of every switch with the host data and the cloud.

    A MAC address is seen on every switch between the device and the firewall;
    the device sits on the port that is not a link to another switch (an edge
    port). Addresses learned only on links to unmonitored switches stay on that
    link.
    """
    ap_by_port = {(a.get('switch'), a['port']): a for a in aps if a.get('port')}
    infra_macs = ({a.get('mac') for a in aps if a.get('mac')} | {sw.get('mac') for sw in switches if sw.get('mac')} |
                  {d.get('mac') for d in (cloud or {}).get('devices', []) if d.get('mac')})
    cloud_clients = {c['mac']: c for c in (cloud or {}).get('clients', []) if c.get('mac')}
    cloud_aps = {d.get('mac'): d.get('name') for d in (cloud or {}).get('devices', []) if d.get('mac')}
    ap_by_mac = dict(cloud_aps, **{a['mac']: a['name'] for a in aps if a.get('mac')})
    multi = len(switches) > 1
    rank = {'device': 0, 'empty': 0, 'ap': 1, 'switch': 2}
    best = {}
    for sw in switches:
        ports = {p['name']: p for p in sw.get('ports', [])}
        # a wired port with a single learned address and a description names that device
        for e in sw.get('fdb', []):
            p = ports.get(e['port'], {})
            role = p.get('role', 'device')
            if role == 'uplink' or e['mac'] in infra_macs:
                continue
            r = rank.get(role, 0)
            if e['mac'] not in best or r < best[e['mac']][0]:
                best[e['mac']] = (r, sw, e, p)
    current = {}
    for mac, (_, sw, e, p) in best.items():
        role = p.get('role', 'device')
        h = hosts.get(mac, {})
        ap = ap_by_port.get((sw['id'], e['port']))
        label = p.get('description', '') if (p.get('mac_count') == 1 and role == 'device') else ''
        rec = {
            'mac': mac, 'vlan': e['vlan'], 'port': e['port'], 'switch': sw['id'],
            'switch_name': sw.get('label', '') if multi else '',
            'connection': 'wireless' if role == 'ap' else 'wired',
            'ap': ap['name'] if ap else '', 'ip': h.get('ip', ''), 'hostname': h.get('hostname', ''),
            'description': h.get('description', ''), 'lease': h.get('source', ''),
            'port_label': label, 'vendor': hostinfo.vendor(mac), 'random_mac': hostinfo.is_random_mac(mac),
            'online': True, 'neighbor': p.get('neighbor') if p.get('mac_count') == 1 else None,
        }
        cc = cloud_clients.get(mac)
        if cc:
            rec.update({'ssid': cc.get('ssid'), 'signal': cc.get('signal'), 'band': cc.get('band'),
                        'snr': cc.get('snr'), 'signal_quality': cc.get('signal_quality'),
                        'ap': ap_by_mac.get(cc.get('ap_mac')) or cc.get('ap') or rec['ap'], 'health': cc.get('health'), 'site': cc.get('site'),
                        'cloud_name': cc.get('name', ''), 'classification': cc.get('classification') or [],
                        'hostname': rec['hostname'] or cc.get('name', '')})
            if cc.get('type') == 'wireless':
                rec['connection'] = 'wireless'
        current[mac] = rec
    # clients reported only by the cloud (behind a mesh AP, or on a switch that is not monitored)
    for mac, cc in cloud_clients.items():
        if mac not in current and mac not in infra_macs:
            h = hosts.get(mac, {})
            current[mac] = {'mac': mac, 'vlan': None, 'port': '', 'switch': '', 'switch_name': '',
                            'connection': cc.get('type') or 'wireless',
                            'ap': ap_by_mac.get(cc.get('ap_mac')) or cc.get('ap', ''), 'ip': cc.get('ip') or h.get('ip', ''),
                            'hostname': h.get('hostname') or cc.get('name', ''), 'description': h.get('description', ''),
                            'lease': h.get('source', ''), 'vendor': hostinfo.vendor(mac),
                            'random_mac': hostinfo.is_random_mac(mac), 'online': True, 'ssid': cc.get('ssid'),
                            'signal': cc.get('signal'), 'band': cc.get('band'), 'health': cc.get('health'),
                            'snr': cc.get('snr'), 'signal_quality': cc.get('signal_quality'), 'site': cc.get('site'),
                            'cloud_name': cc.get('name', ''), 'classification': cc.get('classification') or []}
    for rec in current.values():
        rec.update(devicetype.classify((rec.get('description'), rec.get('hostname'), rec.get('port_label'),
                                        rec.get('cloud_name')), rec.get('vendor'), rec.get('classification'),
                                       rec.pop('neighbor', None)))
    events = []
    for mac, rec in current.items():
        k = known.get(mac)
        if not k:
            known[mac] = k = {'first_seen': now}
            events.append(('info', 'client', 'New device %s%s on %s' % (
                mac, ' (%s)' % (rec['hostname'] or rec['vendor']) if (rec['hostname'] or rec['vendor']) else '',
                rec['ap'] and 'AP %s' % rec['ap'] or 'port %s%s' % (
                    rec['port'], ' on %s' % rec['switch_name'] if rec.get('switch_name') else ''))))
        elif rec['connection'] == 'wireless' and k.get('connection') == 'wireless' and k.get('ap') \
                and rec.get('ap') and k['ap'] != rec['ap']:
            rec['roamed_from'] = k['ap']
        k.update({'last_seen': now, 'port': rec['port'], 'switch': rec.get('switch', ''),
                  'switch_name': rec.get('switch_name', ''), 'type': rec.get('type', ''),
                  'ap': rec['ap'], 'connection': rec['connection'],
                  'ip': rec['ip'] or k.get('ip', ''), 'hostname': rec['hostname'] or k.get('hostname', ''),
                  'vlan': rec['vlan'], 'vendor': rec['vendor'],
                  'port_label': rec.get('port_label') or k.get('port_label', '')})
        rec['first_seen'] = k['first_seen']
        rec['last_seen'] = now
    offline = []
    for mac, k in known.items():
        if mac not in current:
            t = type_info(k.get('type'))
            offline.append({'mac': mac, 'vlan': k.get('vlan'), 'port': k.get('port', ''),
                            'switch': k.get('switch', ''), 'switch_name': k.get('switch_name', ''),
                            'type': t[0], 'type_label': t[1], 'type_icon': t[2], 'type_source': 'history',
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
def _switch_insights(cfg, switch, add):
    """Checks of one switch."""
    skew = switch.get('clock_skew')
    if skew is not None and abs(skew) > cfg.int('general', 'clock_skew_seconds'):
        add('warning', 'switch', 'Switch clock is wrong',
            'The switch clock differs from the firewall by %s. Log timestamps are unreliable. '
            'Configure an SNTP server (e.g. the firewall) on the switch.' % human_duration(abs(skew)))
    servers = switch.get('sntp_list') or []
    if not servers:
        add('warning', 'switch', 'No time server configured on the switch',
            'SNTP has no unicast server. Point it to the firewall so logs and events line up.')
    elif switch.get('time_mode') == 'sntp' and not any(s.get('last_response') for s in servers) \
            and any(s.get('last_request') for s in servers):
        add('warning', 'switch', 'Time server %s does not answer the switch' % ', '.join(s['address'] for s in servers),
            'The switch sends SNTP requests but never got a reply. If the server is this firewall: in '
            'Services > Network Time > General select the interface of the switch network under Interfaces '
            '(or none, to listen everywhere), and allow UDP port 123 to the firewall on that interface.')
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


def insights(cfg, switches, aps, clients, cloud=None):
    out = []

    def add(level, area, title, detail):
        out.append({'level': level, 'area': area, 'title': title, 'detail': detail})

    multi = len(switches) > 1
    for switch in switches:
        if not switch.get('online'):
            add('critical', 'switch', 'Switch %s unreachable' % switch.get('label', switch.get('host')),
                switch.get('error', ''))
            continue
        prefix = '%s: ' % switch.get('label') if multi else ''
        _switch_insights(cfg, switch, lambda level, area, title, detail, p=prefix: add(level, area, p + title, detail))
    for a in aps:
        if not a.get('online'):
            add('critical', 'aps', 'Access point %s unreachable' % a['name'], a.get('error', ''))
            continue
        if a.get('crashed'):
            add('warning', 'aps', '%s restarted after a crash' % a['name'], a.get('reboot_cause', ''))
        if a.get('cloud_status') and a['cloud_status'].upper() != 'CONNECTED':
            add('info', 'aps', '%s not connected to the cloud' % a['name'], a.get('cloud_reason') or a['cloud_status'])
        if not a.get('wired'):
            add('info', 'aps', '%s has no wired link on a monitored switch' % a['name'],
                'It is meshed or connected elsewhere; its wireless clients appear behind its uplink AP.')
    for d in (cloud or {}).get('devices', []):
        weak = d.get('mesh_parent') and (d.get('mesh_quality') in ('poor', 'fair')
                                         or (d.get('mesh_snr') is not None and d['mesh_snr'] < 20))
        if weak:
            add('warning', 'aps', 'Weak mesh link: %s' % d['name'],
                '%s reaches the network wirelessly through %s with SNR %s dB on %s (%s). A cable or a closer '
                'access point would make it faster and more reliable.' % (
                    d['name'], d['mesh_parent'], d.get('mesh_snr'), d.get('mesh_band') or '?',
                    d.get('mesh_quality') or 'weak signal'))
        problems = [p for p in d.get('problems', []) if not (weak and p == 'uplinkFault')]
        if problems and d.get('status') == 'up':
            add('info', 'aps', 'Cloud reports a problem on %s' % d['name'], ', '.join(problems))
    # An access point reports NTP ERROR when its single boot-time attempt failed (often before the network
    # was up); it then takes the time from the cloud. Only a clock that is really wrong is a problem.
    skew_limit = cfg.int('general', 'clock_skew_seconds')
    ntp_fail = [a for a in aps if a.get('online') and a.get('ntp_status', '').upper() == 'ERROR'
                and (a.get('clock_skew') is None or abs(a['clock_skew']) > skew_limit)]
    if ntp_fail:
        servers = sorted({a.get('ntp_server') or '?' for a in ntp_fail})
        add('warning', 'aps', 'Wrong clock on %d access point%s' % (len(ntp_fail), 's' if len(ntp_fail) > 1 else ''),
            '%s could not reach NTP server %s. Make sure the NTP service (Services > Network Time) listens on '
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
def switch_list(state):
    """Switches of a state snapshot (also reads the single-switch format of version 1)."""
    if state.get('switches') is not None:
        return state['switches']
    sw = state.get('switch')
    return [dict(sw, id=sw.get('id', 'default'), label=sw.get('label') or sw.get('name') or sw.get('host', ''))] \
        if sw else []


def diff_events(previous, state):
    ev = []
    old_switches = {s.get('id'): s for s in switch_list(previous)}
    new_switches = switch_list(state)
    multi = len(new_switches) > 1
    for sw in new_switches:
        psw = old_switches.get(sw.get('id')) or {}
        name = sw.get('label') or sw.get('host', '')
        at = (' on %s' % name) if multi else ''
        if psw.get('online') and not sw.get('online'):
            ev.append(('error', 'switch', 'Switch %s unreachable: %s' % (name, sw.get('error', ''))))
        elif psw and not psw.get('online') and sw.get('online'):
            ev.append(('info', 'switch', 'Switch %s reachable again' % name))
        if not (psw.get('online') and sw.get('online')):
            continue
        if sw.get('uptime', 0) + 120 < psw.get('uptime', 0):
            ev.append(('warning', 'switch', 'Switch %srestarted (uptime %s)' % (name + ' ' if multi else '',
                                                                                 human_duration(sw['uptime']))))
        if psw.get('firmware') and sw.get('firmware') and psw['firmware'] != sw['firmware']:
            ev.append(('info', 'switch', 'Switch %s firmware %s -> %s' % (name, psw['firmware'], sw['firmware'])))
        pports = {p['name']: p for p in psw.get('ports', [])}
        for p in sw.get('ports', []):
            old = pports.get(p['name'])
            if not old:
                continue
            label = p['name'] + (' "%s"' % p['description'] if p['description'] else '') + at
            if old['up'] and not p['up']:
                ev.append(('warning' if p.get('role') in ('ap', 'uplink', 'switch') else 'info', 'port',
                           'Port %s down' % label))
            elif not old['up'] and p['up']:
                ev.append(('info', 'port', 'Port %s up at %s Mb/s %s duplex' % (label, p['speed'], p['duplex'])))
            op, np_ = (old.get('poe') or {}).get('status'), (p.get('poe') or {}).get('status')
            if op and np_ and op != np_ and 'fault' in (op, np_):
                ev.append(('warning', 'poe', 'PoE on port %s: %s -> %s' % (label, op, np_)))
        if psw.get('temperature_ok', True) and not sw.get('temperature_ok', True):
            ev.append(('error', 'switch', 'Switch %stemperature alarm (%s C)' % (name + ' ' if multi else '',
                                                                                sw.get('temperature'))))
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
    for key, now in (state.get('sources') or {}).items():
        if not key.startswith('cloud'):
            continue  # switches have their own events above; host and AP sources have none
        was = (previous.get('sources') or {}).get(key, {})
        name = now.get('label') or 'Cloud'
        if was.get('ok') and now.get('enabled') and not now.get('ok'):
            ev.append(('error', 'cloud', 'Cloud %s polling failed: %s' % (name, now.get('error'))))
        elif was.get('enabled') and not was.get('ok') and now.get('ok'):
            ev.append(('info', 'cloud', 'Cloud %s polling recovered' % name))
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
    state = {'generated': now, 'hostname': socket.gethostname(), 'sources': {}, 'version': 2}
    started = time.time()

    hosts = hostinfo.collect()
    state['sources']['host'] = {'enabled': True, 'ok': True, 'detail': ', '.join(hostinfo.available_sources()),
                                'entries': len(hosts)}

    previous_switches = {sw.get('id'): sw for sw in switch_list(previous)}
    devices = cfg.switches()
    if persistent:
        drop_stale_sessions(devices)
    switches = []
    for dev in devices:
        try:
            sw = collect_switch(cfg, dev, previous_switches.get(dev.id), persistent)
            state['sources']['switch:' + dev.id] = {'enabled': True, 'ok': True, 'ms': sw['poll_ms'],
                                                    'label': sw['label'], 'kind': 'switch'}
        except (swlib.SwitchError, OSError, ValueError) as exc:
            state['sources']['switch:' + dev.id] = {'enabled': True, 'ok': False, 'error': str(exc),
                                                    'label': dev.label, 'kind': 'switch'}
            log(syslog.LOG_ERR, 'switch %s: %s' % (dev.label, exc))
            old = previous_switches.get(dev.id) or {}
            sw = {'id': dev.id, 'label': dev.get('name') or old.get('label') or dev.get('host'), 'online': False,
                  'host': dev.get('host'), 'error': str(exc), 'ports': [], 'fdb': [],
                  'model': old.get('model', ''), 'mac': old.get('mac', '')}
        switches.append(sw)
    state['switches'] = switches
    online_switches = [sw for sw in switches if sw.get('online')]

    own_macs = firewall_macs()
    switch_macs = {sw['mac']: sw['id'] for sw in switches if sw.get('mac')}
    by_id = {d.id: d for d in devices}
    for sw in online_switches:
        classify_ports(by_id.get(sw['id']), sw, own_macs, switch_macs)

    aps = []
    if cfg.flag('aps', 'enabled'):
        aps, swarm = collect_aps(cfg, online_switches, hosts)
        state['swarm_size'] = swarm
        state['sources']['aps'] = {'enabled': True, 'ok': all(a['online'] for a in aps) if aps else True,
                                   'entries': len(aps), 'online': sum(1 for a in aps if a['online'])}
    else:
        state['sources']['aps'] = {'enabled': False, 'ok': False}
    state['aps'] = aps

    cloud = None
    for acc in cfg.clouds():
        key = 'cloud:' + acc.id
        try:
            data = cloudlib.InstantOnCloud(acc.get('username'), acc.get('password')).collect(acc.list('sites'))
            for item in data['sites']:
                item['account'] = acc.label
            state['sources'][key] = {'enabled': True, 'ok': True, 'label': acc.label, 'kind': 'cloud',
                                     'sites': [x.get('name') for x in data['sites']]}
            if cloud is None:
                cloud = {'sites': [], 'devices': [], 'clients': [], 'networks': [], 'alerts': []}
            for k in cloud:
                cloud[k].extend(data[k])
        except (cloudlib.CloudError, OSError, ValueError, KeyError) as exc:
            state['sources'][key] = {'enabled': True, 'ok': False, 'error': str(exc), 'label': acc.label,
                                     'kind': 'cloud'}
            log(syslog.LOG_ERR, 'cloud %s: %s' % (acc.label, exc))
    state['cloud'] = cloud
    # the cloud knows the names given in the Instant On app ("AP Rack"); LLDP reports the host name ("AP-Rack")
    cloud_names = {d.get('mac'): d.get('name') for d in (cloud or {}).get('devices', []) if d.get('mac') and d.get('name')}
    for a in aps:
        if cloud_names.get(a.get('mac')) and cloud_names[a['mac']] != a['name']:
            a['local_name'] = a['name']
            a['name'] = cloud_names[a['mac']]

    clients, client_events = build_clients(online_switches, aps, hosts, cloud, known, now)
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
    for d in (cloud or {}).get('devices', []):
        d['clients_seen'] = per_ap.get(d.get('name'), 0)
    state['insights'] = insights(cfg, switches, aps, clients, cloud)
    online = [c for c in clients if c['online']]
    all_ports = [p for sw in online_switches for p in sw.get('ports', [])]
    poe_used = sum((sw.get('poe') or {}).get('used_w') or 0 for sw in online_switches)
    poe_total = sum((sw.get('poe') or {}).get('nominal_w') or 0 for sw in online_switches)
    state['summary'] = {
        'switches_total': len(switches), 'switches_online': len(online_switches),
        'switch_online': bool(switches) and len(online_switches) == len(switches),
        'ports_up': sum(1 for p in all_ports if p['up']),
        'ports_total': len(all_ports),
        'poe_w': round(poe_used, 1) if online_switches else None,
        'poe_nominal_w': poe_total,
        'poe_percent': round(poe_used * 100.0 / poe_total, 1) if poe_total else None,
        'aps_online': sum(1 for a in aps if a['online']), 'aps_total': len(aps),
        'cloud_sites': len((cloud or {}).get('sites', [])),
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
    log(syslog.LOG_INFO, 'poll done in %d ms: switches=%d/%d aps=%d/%d clients=%d events=%d' % (
        state['duration_ms'], state['summary']['switches_online'], state['summary']['switches_total'],
        state['summary']['aps_online'], state['summary']['aps_total'], len(online), len(new_events)))
    return state
