"""
Configuration changes on the switch.

Every change is validated here before anything is sent, checked against the
latest snapshot (the port must exist, the port that leads to the firewall
cannot be switched off) and recorded in the event history and syslog.

Besides the common tasks (ports, PoE, system, time, logging, locator LED,
cable test, restart) any section of the catalogue can be changed through the
generic editor. Sections that control management access are refused; see
``catalog`` for the risk levels.

Access points cannot be changed locally: Instant On access points take their
configuration from the cloud (or the mobile app) and expose no local write
interface.
"""

import re
import time

from . import catalog
from . import switch as swlib

# Daylight saving presets of the switch web interface (recurring rules)
DST_PRESETS = {
    'off': None,
    'eu': {'beginWeek': '06', 'beginDayOfWeek': '01', 'beginMonth': '03', 'beginHour': '01', 'beginMinute': '00',
           'endWeek': '06', 'endDayOfWeek': '01', 'endMonth': '10', 'endHour': '01', 'endMinute': '00'},
    'us': {'beginWeek': '02', 'beginDayOfWeek': '01', 'beginMonth': '03', 'beginHour': '02', 'beginMinute': '00',
           'endWeek': '01', 'endDayOfWeek': '01', 'endMonth': '11', 'endHour': '02', 'endMinute': '00'},
}

PORT_RE = re.compile(r'^\d{1,2}/\d{1,3}$')
TZ_RE = re.compile(r'^([+-])(\d{2}):(\d{2})$')
HOST_RE = re.compile(r'^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$')
IPV4_RE = re.compile(r'^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$')
TZNAME_RE = re.compile(r'^[A-Za-z]{1,4}$')
FIELD_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
SYSNAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9-]{0,56}[A-Za-z0-9])?$')


class ActionError(Exception):
    pass


def _text(value, field, limit):
    value = '' if value is None else str(value)
    if len(value) > limit:
        raise ActionError('%s is longer than %d characters' % (field, limit))
    if re.search(r'[<>&"\x00-\x1f\x7f]', value):
        raise ActionError('%s cannot contain < > & " or control characters' % field)
    return value.strip()


def _flag(value, field):
    if isinstance(value, bool):
        return value
    if str(value).lower() in ('1', 'true', 'yes', 'on'):
        return True
    if str(value).lower() in ('0', 'false', 'no', 'off'):
        return False
    raise ActionError('%s must be true or false' % field)


def _port(state, name):
    name = str(name or '').strip()
    if not PORT_RE.match(name):
        raise ActionError('invalid port name %r' % name)
    for p in ((state or {}).get('switch') or {}).get('ports', []):
        if p.get('name') == name:
            return p
    raise ActionError('port %s is not known; refresh the data and try again' % name)


def uplink_ports(state):
    return {p['name'] for p in ((state or {}).get('switch') or {}).get('ports', []) if p.get('role') == 'uplink'}


def management_vlan(config):
    mgmt = ((config or {}).get('sections') or {}).get('ManagementInterfaceGlobalSetting') or {}
    return str(mgmt.get('managementVLAN') or '1')


def _confirm(params, what):
    if not _flag(params.get('confirm', False), 'Confirm'):
        raise ActionError('%s needs an explicit confirmation' % what)


def _scalar_fields(values, what):
    if not isinstance(values, dict) or not values:
        raise ActionError('no values for %s' % what)
    out = {}
    for key, value in values.items():
        if not FIELD_RE.match(str(key)):
            raise ActionError('invalid field name %r' % key)
        if isinstance(value, (dict, list)):
            raise ActionError('field %s cannot be edited here' % key)
        out[key] = _text(value, key, 256)
    return out


def plan_section(params, state, config):
    """Generic change of one catalogue section."""
    name = str(params.get('section') or '')
    meta = catalog.info(name)
    if not meta:
        raise ActionError('unknown section %r' % name)
    if meta['risk'] == 'blocked':
        raise ActionError('%s controls access to the switch and can only be changed from the switch web '
                          'interface' % meta['title'])
    if meta['risk'] == 'caution':
        _confirm(params, 'Changing "%s"' % meta['title'])
    op = str(params.get('op') or 'set')
    if meta['kind'] == 'setting':
        if op != 'set':
            raise ActionError('%s only supports changes' % meta['title'])
        values = _scalar_fields(params.get('values'), meta['title'])
        return [(name, 'set', values)], '%s: %s' % (meta['title'], ', '.join(
            '%s=%s' % kv for kv in sorted(values.items())))
    if op not in ('set', 'add', 'delete', 'deleteAll'):
        raise ActionError('invalid operation %r' % op)
    row = str(params.get('row') or meta['row'] or 'Entry')
    if not FIELD_RE.match(row):
        raise ActionError('invalid row name %r' % row)
    if op == 'deleteAll':
        _confirm(params, 'Deleting every row of "%s"' % meta['title'])
        return [(name, 'deleteAll', {row: {}})], '%s: all rows deleted' % meta['title']
    entries = params.get('entries')
    if not isinstance(entries, list) or not entries or len(entries) > 64:
        raise ActionError('give between 1 and 64 rows')
    entries = [_scalar_fields(e, meta['title']) for e in entries]
    uplinks = uplink_ports(state)
    mvlan = management_vlan(config)
    for e in entries:
        for f in catalog.PORT_FIELDS:
            if e.get(f) in uplinks:
                raise ActionError('port %s leads to the firewall; it cannot be changed here' % e[f])
        if name in ('VLANList', 'VLANInterfaceISList', 'VLANInterfaceList', 'MSTPVLANList') and \
                str(e.get('VLANID', e.get('vlanId', ''))) == mvlan and op in ('delete', 'set'):
            raise ActionError('VLAN %s is the management VLAN of the switch' % mvlan)
    keys = ', '.join(' '.join('%s=%s' % (k, e[k]) for k in catalog.KEY_FIELDS if k in e) or '?' for e in entries)
    verb = {'set': 'changed', 'add': 'added', 'delete': 'deleted'}[op]
    return [(name, op, {row: entries})], '%s: %s %s' % (meta['title'], verb, keys)


def _label(port):
    return port['name'] + (' "%s"' % port['description'] if port.get('description') else '')


def plan(action, params, state, config=None):
    """Validate one request. Returns (changes, summary) without touching the switch.

    ``changes`` is the list of (section, action, payload) for
    InstantOnSwitch.apply; an empty list with action 'save' means "save only".
    """
    params = params or {}
    if action == 'port':
        port = _port(state, params.get('port'))
        entry = {'interfaceName': port['name']}
        notes = []
        if 'description' in params:
            entry['interfaceDescription'] = _text(params['description'], 'Description', 64)
            if entry['interfaceDescription'] != port.get('description', ''):
                notes.append('description "%s"' % entry['interfaceDescription'])
        if 'enabled' in params:
            enabled = _flag(params['enabled'], 'Enabled')
            if not enabled and port.get('role') == 'uplink':
                raise ActionError('port %s leads to the firewall; switching it off would cut the connection '
                                  'to the switch' % port['name'])
            entry['adminState'] = '1' if enabled else '2'
            if enabled != port.get('enabled'):
                notes.append('enabled' if enabled else 'disabled')
        if len(entry) == 1:
            raise ActionError('nothing to change')
        return [('Standard802_3List', 'set', {'Entry': entry})], \
            'Port %s: %s' % (_label(port), ', '.join(notes) or 'unchanged')
    if action == 'poe':
        port = _port(state, params.get('port'))
        if not port.get('poe'):
            raise ActionError('port %s does not support PoE' % port['name'])
        enabled = _flag(params.get('enabled'), 'PoE')
        return [('PoEPSEInterfaceList', 'set', {'Interface': {'interfaceName': port['name'],
                                                              'adminEnable': '1' if enabled else '2'}})], \
            'Port %s: PoE %s' % (_label(port), 'enabled' if enabled else 'disabled')
    if action == 'poe_cycle':
        port = _port(state, params.get('port'))
        if not port.get('poe'):
            raise ActionError('port %s does not support PoE' % port['name'])
        if not (port.get('poe') or {}).get('enabled'):
            raise ActionError('PoE is disabled on port %s' % port['name'])
        return [('PoEPSEInterfaceList', 'set', {'Interface': {'interfaceName': port['name'],
                                                              'powerReActivate': '1'}})], \
            'Port %s: PoE power cycled' % _label(port)
    if action == 'system':
        entry, notes = {}, []
        if params.get('name') not in (None, ''):
            name = _text(params['name'], 'Name', 58)
            if not SYSNAME_RE.match(name):
                raise ActionError('the switch name may contain letters, digits and hyphens only')
            entry['systemName'] = name
            notes.append('name "%s"' % name)
        for key, field in (('location', 'systemLocation'), ('contact', 'systemContact')):
            if key in params:
                entry[field] = _text(params[key], key.capitalize(), 160)
                notes.append('%s "%s"' % (key, entry[field]))
        if not entry:
            raise ActionError('nothing to change')
        return [('SystemGlobalSetting', 'set', entry)], 'Switch ' + ', '.join(notes)
    if action == 'time':
        server = str(params.get('sntp_server') or '').strip()
        if server and not (IPV4_RE.match(server) or HOST_RE.match(server)):
            raise ActionError('invalid time server %r' % server)
        tz = str(params.get('timezone') or '+00:00').strip()
        m = TZ_RE.match(tz)
        if not m or int(m.group(2)) > 14 or m.group(3) not in ('00', '30', '45'):
            raise ActionError('invalid time zone offset %r (use +01:00)' % tz)
        # the switch stores junk when the abbreviation is left out, so always send one
        tz_name = str(params.get('timezone_name') or
                      ((state or {}).get('switch') or {}).get('timezone_name') or 'UTC').strip()
        if not TZNAME_RE.match(tz_name):
            raise ActionError('the time zone abbreviation must be 1 to 4 letters, for example CET')
        dst = str(params.get('dst') or 'off')
        if dst not in DST_PRESETS:
            raise ActionError('daylight saving must be one of %s' % ', '.join(DST_PRESETS))
        current = ((state or {}).get('switch') or {}).get('sntp_list') or []
        setting = {'setTimeMode': '2' if server else '1',
                   'dayLightSavingMode': '1' if DST_PRESETS[dst] else '3',
                   'TimeZone': {'offsetHour': m.group(1) + m.group(2), 'offsetMinute': m.group(3),
                                'timeZoneID': tz_name}}
        if DST_PRESETS[dst]:
            setting['DayLightSaving'] = {'RecurrentPeriod': dict(DST_PRESETS[dst]), 'timeOffset': '60'}
        changes = [('TimeSetting', 'set', setting)]
        old = [s['address'] for s in current if s.get('address') and s['address'] != server]
        if old:
            changes.append(('SNTPServerTable', 'delete', {'SNTPServerEntry': [{'IPAddress': a} for a in old]}))
        if server and server not in [s.get('address') for s in current]:
            changes.append(('SNTPServerTable', 'set', {'SNTPServerEntry': {'IPAddress': server,
                                                                           'pollIntervalEnabled': '1'}}))
        return changes, 'Switch time: %s, time zone %s (UTC%s), daylight saving %s' % (
            'SNTP server %s' % server if server else 'manual clock', tz_name, tz, dst)
    if action == 'syslog':
        enabled = _flag(params.get('enabled', True), 'Enabled')
        changes = [('SyslogServerList', 'deleteAll', {'SyslogServer': {}})]
        if not enabled:
            return changes, 'Remote syslog switched off'
        server = str(params.get('server') or '').strip()
        if not IPV4_RE.match(server):
            raise ActionError('the syslog server must be an IPv4 address')
        port = str(params.get('port') or '514').strip()
        if not port.isdigit() or not 1 <= int(port) <= 65535:
            raise ActionError('invalid syslog port %r' % port)
        severity = str(params.get('severity') or '6').strip()
        if severity not in [str(i) for i in range(8)]:
            raise ActionError('severity must be 0 (emergency) to 7 (debug)')
        changes.append(('SyslogServerList', 'set', {'SyslogServer': {
            'addrType': '1', 'IPAddr': server, 'portNo': port, 'severity': severity}}))
        changes.insert(0, ('SyslogGlobalSetting', 'set', {'enable': '1'}))
        return changes, 'Remote syslog to %s:%s (level %s and worse)' % (server, port, severity)
    if action == 'locate':
        on = _flag(params.get('on', True), 'On')
        return [('LocateUnit', 'set', {'duration': '1800' if on else '0', 'unitID': '1' if on else '0'})], \
            'Locator LED %s' % ('blinking for 30 minutes' if on else 'off')
    if action == 'cable_test':
        port = _port(state, params.get('port'))
        if port.get('role') == 'uplink':
            raise ActionError('port %s leads to the firewall; testing it would interrupt the connection' % port['name'])
        _confirm(params, 'A cable test (the link drops for a few seconds)')
        return [('CableTestPortList', 'set', {'Entry': {'interfaceName': port['name']}})], \
            'Cable test started on port %s' % _label(port)
    if action == 'reboot':
        _confirm(params, 'Restarting the switch')
        return [('Reload', 'set', {'UnitList': {'UnitEntry': {'unitID': '0'}}})], \
            'Switch restart requested (the network is down for about two minutes)'
    if action == 'section':
        return plan_section(params, state, config)
    if action == 'save':
        return [], 'Switch configuration saved to startup'
    raise ActionError('unknown action %r' % action)


def execute(client, action, params, state, save=True, config=None):
    """Validate and apply one change. Returns a result dict."""
    changes, summary = plan(action, params, state, config)
    started = time.time()
    if action == 'reboot':
        # keep the running configuration, then restart; the session ends with the reboot
        if save:
            client.save_config()
        try:
            client.apply(changes)
        except swlib.SwitchError:
            pass
        client.logged_in = False
        return {'status': 'ok', 'message': summary, 'saved': save, 'ms': int((time.time() - started) * 1000)}
    if action in ('locate', 'cable_test'):
        client.apply(changes)
        return {'status': 'ok', 'message': summary, 'saved': None, 'ms': int((time.time() - started) * 1000)}
    if changes:
        client.apply(changes)
    saved = False
    if action == 'save' or (save and changes):
        try:
            client.save_config()
            saved = True
        except swlib.SwitchError as exc:
            if action == 'save':
                raise
            summary += ' (not saved: %s)' % exc
    return {'status': 'ok', 'message': summary, 'saved': saved, 'ms': int((time.time() - started) * 1000)}
