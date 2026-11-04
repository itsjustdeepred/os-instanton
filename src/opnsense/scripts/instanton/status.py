#!/usr/local/bin/python3
"""
Print the cached Instant On state as JSON for configd / the API.

usage: status.py <view>[:<switch id>]

views: summary, switch, ports, log (these three take a switch id; without
one the first switch is used), aps, clients, events, insights, topology, all
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import topology  # noqa: E402
from lib.collector import load_json, switch_list  # noqa: E402
from lib.config import Config  # noqa: E402

HEAVY = ('fdb', 'log')


def brief(sw):
    return {k: v for k, v in sw.items() if k not in HEAVY}


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else 'summary'
    what, _, ident = arg.partition(':')
    if ident and not re.match(r'^[A-Za-z0-9-]{1,64}$', ident):
        print(json.dumps({'error': 'invalid switch id'}))
        return 0
    cfg = Config()
    state = load_json('state.json', {})
    age = int(time.time() - state['generated']) if state.get('generated') else None
    switches = switch_list(state)
    meta = {'generated': state.get('generated'), 'age': age, 'interval': cfg.int('general', 'interval'),
            'enabled': cfg.flag('general', 'enabled'), 'configured': cfg.loaded, 'sources': state.get('sources', {}),
            'allow_changes': cfg.flag('general', 'allow_changes'),
            'switches': [{'id': s.get('id'), 'label': s.get('label') or s.get('host'), 'online': bool(s.get('online')),
                          'model': s.get('model', '')} for s in switches]}
    selected = next((s for s in switches if s.get('id') == ident), None) if ident else (switches[0] if switches else None)
    cloud = state.get('cloud') or {}
    if what == 'summary':
        out = {'summary': state.get('summary', {}), 'insights': state.get('insights', []),
               'switches': [brief(s) for s in switches],
               'aps': state.get('aps', []), 'swarm_size': state.get('swarm_size'),
               'events': load_json('events.json', [])[-10:][::-1],
               'cloud': {k: cloud.get(k, []) for k in ('sites', 'networks', 'alerts')} if cloud else None}
    elif what == 'switch':
        out = {'switch': brief(selected) if selected else None}
    elif what == 'ports':
        out = {'ports': (selected or {}).get('ports', []), 'poe': (selected or {}).get('poe')}
    elif what == 'log':
        out = {'log': (selected or {}).get('log', [])}
    elif what == 'aps':
        out = {'aps': state.get('aps', []), 'swarm_size': state.get('swarm_size'),
               'cloud_devices': cloud.get('devices', []), 'cloud_networks': cloud.get('networks', []),
               'cloud_sites': cloud.get('sites', []), 'cloud_alerts': cloud.get('alerts', [])}
    elif what == 'clients':
        out = {'clients': state.get('clients', [])}
    elif what == 'events':
        out = {'events': load_json('events.json', [])[::-1]}
    elif what == 'insights':
        out = {'insights': state.get('insights', [])}
    elif what == 'topology':
        out = topology.build(state, switches) if state else {'nodes': []}
    elif what == 'all':
        out = dict(state)
    else:
        out = {'error': 'unknown view %s' % what}
    out['meta'] = meta
    print(json.dumps(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
