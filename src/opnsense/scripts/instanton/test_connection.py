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
    if cfg.flag('switch', 'enabled') and cfg.get('switch', 'host'):
        try:
            client = swlib.InstantOnSwitch(cfg.get('switch', 'host'), cfg.get('switch', 'username'),
                                           cfg.get('switch', 'password'), verify_tls=cfg.flag('switch', 'verify_tls'))
            with client:
                info = client.fetch('SystemGlobalSetting').get('SystemGlobalSetting', {})
            result['switch'] = {'ok': True, 'message': '%s, firmware %s' % (
                info.get('systemDescription', '').split(',')[0], info.get('firmwareVersion', ''))}
        except swlib.SwitchError as exc:
            result['switch'] = {'ok': False, 'message': str(exc)}
    else:
        result['switch'] = {'ok': None, 'message': 'not configured'}
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
        result['aps'] = {'ok': ok, 'message': '; '.join(msgs)}
    elif cfg.flag('aps', 'enabled') and cfg.flag('aps', 'discover'):
        result['aps'] = {'ok': None, 'message': 'access points are discovered through the switch (LLDP)'}
    if cfg.flag('cloud', 'enabled') and cfg.get('cloud', 'username'):
        try:
            client = cloudlib.InstantOnCloud(cfg.get('cloud', 'username'), cfg.get('cloud', 'password'))
            sites = client.sites()
            result['cloud'] = {'ok': True, 'message': 'sites: %s' % ', '.join(str(s.get('name')) for s in sites)}
        except cloudlib.CloudError as exc:
            result['cloud'] = {'ok': False, 'message': str(exc)}
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
