#!/usr/local/bin/python3
"""
Manage the Wi-Fi networks of an Instant On site through the cloud.

usage: cloudnet.py <base64url JSON request>

request: {"op": "list" | "save" | "delete", "account": <account id>, "site": <site id>,
          "id": <network id, for save of an existing network and delete>,
          "network": {<fields to set>}}

Changes need "Allow changes" in the settings. The Wi-Fi passphrase is never
returned: an empty passphrase on save keeps the current one. Every change is
written to the event history and the log.
"""

import base64
import json
import os
import re
import sys
import syslog
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import cloud as cloudlib  # noqa: E402
from lib.collector import load_json, log, save_json  # noqa: E402
from lib.config import Config  # noqa: E402

ID_RE = re.compile(r'^[A-Za-z0-9-]{1,64}$')
BOOLEANS = ['isEnabled', 'isSsidHidden', 'useVlan', 'isAvailableOn24GHzRadioBand', 'isAvailableOn5GHzRadioBand',
            'isAvailableOn6GHzRadioBand', 'isLegacy80211bRatesEnabled', 'isHighEfficiency11axEnabled',
            'isHighEfficiency11axOfdmaEnabled', 'isDynamicMulticastOptimizationEnabled', 'isInternetAllowed',
            'isIntraSubnetTrafficAllowed', 'blockPrivateSubnets']
# counters and state the cloud computes; they are not sent back
READ_ONLY = {'health', 'healthConditions', 'wirelessClientsCount', 'wireless24GHzClientsCount', 'wireless5GHzClientsCount',
             'wireless6GHzClientsCount', 'downstreamThroughputInBitsPerSecond', 'upstreamThroughputInBitsPerSecond',
             'applicationCategoryUsage', 'applicationsDataPending', 'kind', 'capabilities', 'activeSchedule',
             'networkActivationEffectivePolicy', 'isDeletable', 'bssIndex'}


class RequestError(Exception):
    pass


def decode(arg):
    try:
        data = json.loads(base64.urlsafe_b64decode(arg + '=' * (-len(arg) % 4)).decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise RequestError('malformed request')
    if not isinstance(data, dict):
        raise RequestError('malformed request')
    return data


def public(net):
    """A network as shown to the page: no passphrase, no usage statistics."""
    out = {k: v for k, v in net.items() if k not in ('preSharedKey', 'applicationCategoryUsage', 'allowList')}
    out['hasPassphrase'] = bool(net.get('preSharedKey'))
    return out


def clean(changes):
    """Validate and normalise the fields a request may change."""
    out = {}
    if 'networkName' in changes:
        name = str(changes['networkName']).strip()
        if not 1 <= len(name) <= 32:
            raise RequestError('the network name needs 1 to 32 characters')
        out['networkName'] = name
    if changes.get('preSharedKey'):
        psk = str(changes['preSharedKey'])
        if not 8 <= len(psk) <= 63 or any(ord(c) < 32 or ord(c) > 126 for c in psk):
            raise RequestError('the Wi-Fi password needs 8 to 63 printable characters')
        out['preSharedKey'] = psk
    if 'type' in changes:
        if changes['type'] not in ('employee', 'guest'):
            raise RequestError('unknown network use')
        out['type'] = changes['type']
    if 'security' in changes:
        if changes['security'] not in ('wpa2', 'wpa3'):
            raise RequestError('only WPA2 Personal and WPA2 + WPA3 Personal can be set here')
        out['security'] = changes['security']
    for key in BOOLEANS:
        if key in changes:
            out[key] = bool(changes[key])
    if 'vlanId' in changes and changes['vlanId'] not in (None, ''):
        try:
            vlan = int(changes['vlanId'])
        except (TypeError, ValueError):
            raise RequestError('the VLAN must be a number')
        if not 1 <= vlan <= 4094:
            raise RequestError('the VLAN must be between 1 and 4094')
        out['vlanId'] = vlan
    if 'qos' in changes and isinstance(changes['qos'], dict):
        q = changes['qos']
        qos = {}
        for key in ('isBandwidthLimitEnabled', 'isDownloadBandwidthLimitEnabled', 'isUploadBandwidthLimitEnabled',
                    'isTrafficPriorityEnabled'):
            if key in q:
                qos[key] = bool(q[key])
        for key in ('downloadBandwidthLimitInMbps', 'uploadBandwidthLimitInMbps'):
            if key in q:
                try:
                    value = int(q[key])
                except (TypeError, ValueError):
                    raise RequestError('bandwidth limits are whole Mb/s')
                if not 1 <= value <= 1000:
                    raise RequestError('bandwidth limits go from 1 to 1000 Mb/s')
                qos[key] = value
        if q.get('bandwidthLimitMode') in ('perClient', 'perNetwork'):
            qos['bandwidthLimitMode'] = q['bandwidthLimitMode']
        if q.get('trafficPriority') in ('low', 'medium', 'high'):
            qos['trafficPriority'] = q['trafficPriority']
        out['qos'] = qos
    if 'boundAccessPoints' in changes:
        if not isinstance(changes['boundAccessPoints'], list):
            raise RequestError('malformed list of access points')
        out['boundAccessPoints'] = [str(x).lower() for x in changes['boundAccessPoints']]
    return out


def apply_changes(net, changes):
    """Merge validated changes into a full network object."""
    bound = changes.pop('boundAccessPoints', None)
    qos = changes.pop('qos', None)
    net.update(changes)
    if qos:
        net['qos'] = dict(net.get('qos') or {}, **qos)
        q = net['qos']
        # the older top-level copies of the limits are kept in step with qos
        net['isBandwidthLimitEnabled'] = bool(q.get('isBandwidthLimitEnabled'))
        if q.get('bandwidthLimitMode'):
            net['bandwidthLimitMode'] = q['bandwidthLimitMode']
        if q.get('downloadBandwidthLimitInMbps'):
            net['perClientBandwidthLimitInMbps'] = q['downloadBandwidthLimitInMbps']
            q['perClientDownloadBandwidthLimitInMbps'] = q['downloadBandwidthLimitInMbps']
        if q.get('uploadBandwidthLimitInMbps'):
            net['perClientUploadBandwidthLimitInMbps'] = q['uploadBandwidthLimitInMbps']
            q['perClientUploadBandwidthLimitInMbps'] = q['uploadBandwidthLimitInMbps']
    if bound is not None:
        for ap in net.get('accessPoints') or []:
            ap['isBoundToNetwork'] = str(ap.get('deviceId', '')).lower() in bound
        net['isBroadcastOnAllBoundApsOnAllBands'] = all(ap.get('isBoundToNetwork') for ap in net.get('accessPoints') or [])
    if not net.get('useVlan'):
        net['vlanId'] = None
    return net


def new_network(existing, changes):
    """A network as the portal wizard creates it, with the requested fields."""
    template = existing[0] if existing else {}
    aps = [dict({k: ap.get(k) for k in ('deviceId', 'deviceName', 'deviceModel', 'radioBandMapping', 'enabledRadioBands')},
                isBoundToNetwork=True) for ap in template.get('accessPoints') or []]
    net = {
        'authentication': 'psk', 'security': 'wpa3', 'networkName': '', 'isEnabled': True, 'useVlan': False,
        'vlanId': None, 'wiredNetworkId': None, 'isSsidHidden': False, 'isWireless': True, 'type': 'employee',
        'preSharedKey': '', 'isCaptivePortalEnabled': False, 'ipAddressingMode': 'network',
        'isAvailableOn24GHzRadioBand': True, 'isAvailableOn5GHzRadioBand': True, 'isAvailableOn6GHzRadioBand': False,
        'isLegacy80211bRatesEnabled': False, 'isHighEfficiency11axEnabled': True, 'isHighEfficiency11axOfdmaEnabled': False,
        'isExtremelyHighThroughput11beEnabled': False, 'isExtremelyHighThroughput11beMloEnabled': False,
        'isDynamicMulticastOptimizationEnabled': False, 'isBroadcastOnAllBoundApsOnAllBands': True, 'accessPoints': aps,
    }
    net = apply_changes(net, changes)
    if not net['networkName']:
        raise RequestError('the network needs a name')
    if not net.get('preSharedKey'):
        raise RequestError('a new network needs a Wi-Fi password')
    if net.get('useVlan') and not net.get('vlanId'):
        raise RequestError('choose the VLAN of the network')
    return net


def record(cfg, level, message):
    events = load_json('events.json', [])
    events.append({'time': time.time(), 'level': level, 'area': 'change', 'message': message})
    save_json('events.json', events[-cfg.int('general', 'event_limit'):])
    log(syslog.LOG_NOTICE if level == 'info' else syslog.LOG_ERR, '[change] %s' % message)


def main():
    cfg = Config()
    try:
        if len(sys.argv) < 2:
            raise RequestError('no request')
        req = decode(sys.argv[1])
        op = req.get('op')
        account, site = str(req.get('account') or ''), str(req.get('site') or '')
        if op not in ('list', 'save', 'delete') or not ID_RE.match(account) or not ID_RE.match(site):
            raise RequestError('invalid request')
        if op != 'list' and not cfg.flag('general', 'allow_changes'):
            raise RequestError('changes are disabled; enable "Allow changes" in Services > Instant On > Settings')
        acc = next((a for a in cfg.clouds() if a.id == account), None)
        if acc is None:
            raise RequestError('unknown cloud account')
        client = cloudlib.InstantOnCloud(acc.get('username'), acc.get('password'))
        networks = client.networks(site)
        if op == 'list':
            print(json.dumps({'status': 'ok', 'networks': [public(n) for n in networks]}))
            return 0
        net_id = str(req.get('id') or '')
        if net_id and not ID_RE.match(net_id):
            raise RequestError('invalid network')
        current = next((n for n in networks if n.get('id') == net_id), None)
        if net_id and current is None:
            raise RequestError('the network no longer exists')
        if op == 'delete':
            if not current.get('isDeletable', True):
                raise RequestError('the cloud does not allow deleting this network')
            client.delete_network(site, net_id)
            record(cfg, 'info', 'Wi-Fi network "%s" deleted' % current.get('networkName'))
            print(json.dumps({'status': 'ok'}))
            return 0
        changes = clean(req.get('network') or {})
        if current is None:
            body = new_network([n for n in networks if n.get('isWireless')], changes)
            created = client.create_network(site, body)
            record(cfg, 'info', 'Wi-Fi network "%s" created%s%s' % (
                body['networkName'], ' on VLAN %s' % body['vlanId'] if body.get('useVlan') else '',
                ', hidden' if body.get('isSsidHidden') else ''))
            print(json.dumps({'status': 'ok', 'network': public(created or body)}))
            return 0
        what = ', '.join(sorted(k for k in changes if k != 'preSharedKey')) + (', password' if 'preSharedKey' in changes else '')
        body = {k: v for k, v in current.items() if k not in READ_ONLY}
        body = apply_changes(body, changes)
        updated = client.update_network(site, net_id, body)
        record(cfg, 'info', 'Wi-Fi network "%s" changed: %s' % (body.get('networkName'), what or 'no field'))
        print(json.dumps({'status': 'ok', 'network': public(updated or body)}))
    except (RequestError, cloudlib.CloudError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
