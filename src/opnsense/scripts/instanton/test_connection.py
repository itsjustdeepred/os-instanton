#!/usr/local/bin/python3
"""
Check that every configured source answers, without storing anything.
Prints one JSON object with a result per source.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ap as aplib  # noqa: E402
from lib import cloud as cloudlib  # noqa: E402
from lib import switch as swlib  # noqa: E402
from lib.config import Config  # noqa: E402


def main():
    cfg = Config()
    result = {}
    for dev in cfg.switches():
        key = 'switch:' + dev.id
        try:
            client = swlib.InstantOnSwitch(dev.get('host'), dev.get('username'), dev.get('password'),
                                           verify_tls=dev.flag('verify_tls'))
            with client:
                info = client.fetch('SystemGlobalSetting').get('SystemGlobalSetting', {})
            result[key] = {'ok': True, 'label': 'Switch %s' % dev.label, 'message': '%s "%s", firmware %s' % (
                info.get('systemDescription', '').split(',')[0], info.get('systemName', ''),
                info.get('firmwareVersion', ''))}
        except swlib.SwitchError as exc:
            result[key] = {'ok': False, 'label': 'Switch %s' % dev.label, 'message': str(exc)}
    if not cfg.switches():
        result['switch'] = {'ok': None, 'label': 'Switches', 'message': 'none configured'}
    hosts = cfg.list('aps', 'hosts')
    if cfg.flag('aps', 'enabled') and hosts:
        msgs, ok = [], True
        for host in hosts:
            try:
                info = aplib.read_ap(host, port=cfg.int('aps', 'port'))
                msgs.append('%s: %s %s' % (host, info.get('model', '?'), info.get('firmware', '')))
            except aplib.APError as exc:
                ok = False
                msgs.append(str(exc))
        result['aps'] = {'ok': ok, 'label': 'Access points', 'message': '; '.join(msgs)}
    elif cfg.flag('aps', 'enabled') and cfg.flag('aps', 'discover'):
        result['aps'] = {'ok': None, 'label': 'Access points',
                         'message': 'access points are discovered through the switches (LLDP)'}
    for acc in cfg.clouds():
        key = 'cloud:' + acc.id
        try:
            client = cloudlib.InstantOnCloud(acc.get('username'), acc.get('password'))
            sites = client.sites()
            chosen = client.select_sites(acc.list('sites')) if acc.list('sites') else sites
            names = {s.get('id') for s in chosen}
            result[key] = {'ok': True, 'label': 'Cloud %s' % acc.label, 'message': 'sites: %s' % ', '.join(
                '%s%s' % (s.get('name'), '' if s.get('id') in names else ' (not selected)') for s in sites)}
        except cloudlib.CloudError as exc:
            result[key] = {'ok': False, 'label': 'Cloud %s' % acc.label, 'message': str(exc)}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
