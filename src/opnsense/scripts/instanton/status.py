#!/usr/local/bin/python3
"""
Print the cached Instant On state as JSON for configd / the API.

usage: status.py [summary|switch|ports|aps|clients|events|log|insights|all]
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.collector import load_json  # noqa: E402
from lib.config import Config  # noqa: E402


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else 'summary'
    cfg = Config()
    state = load_json('state.json', {})
    age = int(time.time() - state['generated']) if state.get('generated') else None
    meta = {'generated': state.get('generated'), 'age': age, 'interval': cfg.int('general', 'interval'),
            'enabled': cfg.flag('general', 'enabled'), 'configured': cfg.loaded, 'sources': state.get('sources', {})}
    switch = dict(state.get('switch') or {})
    if what == 'summary':
        out = {'summary': state.get('summary', {}), 'insights': state.get('insights', []),
               'switch': {k: v for k, v in switch.items() if k not in ('ports', 'fdb', 'log')},
               'aps': state.get('aps', []), 'swarm_size': state.get('swarm_size'),
               'events': load_json('events.json', [])[-10:][::-1],
               'cloud': {k: v for k, v in (state.get('cloud') or {}).items() if k in ('site', 'networks', 'alerts')}}
    elif what == 'switch':
        out = {'switch': {k: v for k, v in switch.items() if k not in ('fdb', 'log')}}
    elif what == 'ports':
        out = {'ports': switch.get('ports', []), 'poe': switch.get('poe')}
    elif what == 'aps':
        out = {'aps': state.get('aps', []), 'swarm_size': state.get('swarm_size'),
               'cloud_devices': (state.get('cloud') or {}).get('devices', [])}
    elif what == 'clients':
        out = {'clients': state.get('clients', [])}
    elif what == 'events':
        out = {'events': load_json('events.json', [])[::-1]}
    elif what == 'log':
        out = {'log': switch.get('log', [])}
    elif what == 'insights':
        out = {'insights': state.get('insights', [])}
    elif what == 'all':
        out = dict(state)
    else:
        out = {'error': 'unknown view %s' % what}
    out['meta'] = meta
    print(json.dumps(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
