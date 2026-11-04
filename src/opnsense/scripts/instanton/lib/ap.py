"""
Read the local diagnostic page of HPE Networking Instant On access points.

Instant On APs expose ``/swarm.cgi?opcode=smb_debug_info`` on port 8080
without authentication. It returns basic identity and health data (model,
serial, firmware, uplink, cloud connection state, last reboot reason).
Wireless client lists are not available locally; they require the cloud
portal.
"""

import re
import urllib.error
import urllib.request
from html import unescape

FIELD_MAP = {
    'IP Address': 'ip',
    'Netmask': 'netmask',
    'Gateway': 'gateway',
    'DNS': 'dns',
    'Master Device': 'master',
    'Device count': 'swarm_size',
    'Uplink Type': 'uplink_type',
    'Management VLAN': 'mgmt_vlan',
    'Current Time': 'time',
    'NTP Status': 'ntp_status',
    'NTP Server': 'ntp_server',
    'NTP Log': 'ntp_log',
    'Time source': 'time_source',
    'Onboarding Status': 'onboarding',
    'Cloudconnect Status': 'cloud_status',
    'Cloudconnect Reason': 'cloud_reason',
    'Firmware Version': 'firmware',
    'Firmware Build Number': 'firmware_build',
    'AP Model': 'model',
    'Serial Number': 'serial',
    'Reboot Cause': 'reboot_cause',
    'Lua Current State': 'state',
    'CLI Swarm State': 'swarm_state',
}


class APError(Exception):
    pass


def parse_debug_info(text):
    raw = {}
    for name, value in re.findall(r'<data name="([^"]*)"[^>]*>(.*?)</data>', text, re.S):
        raw[unescape(name).strip()] = unescape(value).strip()
    info = {}
    for src, dst in FIELD_MAP.items():
        if src in raw:
            info[dst] = raw[src]
    if 'master' in info:
        info['master'] = info['master'].lower() == 'true'
    if 'swarm_size' in info:
        try:
            info['swarm_size'] = int(info['swarm_size'])
        except ValueError:
            pass
    cause = info.get('reboot_cause', '')
    info['reboot_cause'] = re.sub(r'^AP Reboot reason:\s*', '', cause)
    info['crashed'] = 'panic' in cause.lower() or 'assert' in cause.lower()
    info['raw'] = raw
    return info


def read_ap(host, port=8080, timeout=6):
    url = 'http://%s:%d/swarm.cgi?ip=127.0.0.1&refresh=false&opcode=smb_debug_info&loadPageData=true' % (host, port)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read().decode('utf-8', 'replace')
    except (urllib.error.URLError, OSError) as exc:
        raise APError('%s unreachable: %s' % (host, getattr(exc, 'reason', exc)))
    if '<re>' not in text and '<data name=' not in text:
        raise APError('%s did not return Instant On diagnostic data' % host)
    return parse_debug_info(text)
