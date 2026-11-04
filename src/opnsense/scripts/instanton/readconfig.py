#!/usr/local/bin/python3
"""
Read switch configuration sections for the configuration editor.

usage: readconfig.py [<group>|<Section>|all|cached]

The sections are read live (one login), merged into
/var/db/instanton/config.json and printed as JSON together with the
catalogue (group, kind, risk, title of every section). ``cached`` prints
the stored copy without contacting the switch.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import catalog  # noqa: E402
from lib import switch as swlib  # noqa: E402
from lib.collector import load_json, save_json  # noqa: E402
from lib.config import Config  # noqa: E402


def read_sections(cfg, names):
    """Read ``names`` in one session. Returns (data, errors)."""
    client = swlib.InstantOnSwitch(cfg.get('switch', 'host'), cfg.get('switch', 'username'),
                                   cfg.get('switch', 'password'), verify_tls=cfg.flag('switch', 'verify_tls'))
    data, errors = {}, {}
    with client:
        for i in range(0, len(names), catalog.READ_BATCH):
            chunk = names[i:i + catalog.READ_BATCH]
            try:
                data.update(client.fetch(*chunk))
            except swlib.SwitchError:
                for name in chunk:
                    try:
                        data.update(client.fetch(name))
                    except swlib.SwitchError as exc:
                        errors[name] = str(exc)
    for name in names:
        if name not in data and name not in errors:
            errors[name] = 'not supported by this firmware'
    return data, errors


def merge(data, errors):
    cache = load_json('config.json', {})
    sections = cache.get('sections', {})
    read_at = cache.get('read_at', {})
    now = time.time()
    for name, value in data.items():
        sections[name] = value
        read_at[name] = now
    for name in errors:
        sections.pop(name, None)
        read_at.pop(name, None)
    cache.update({'sections': sections, 'read_at': read_at, 'errors': dict(cache.get('errors', {}), **errors)})
    for name in data:
        cache['errors'].pop(name, None)
    save_json('config.json', cache)
    return cache


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else 'cached'
    cfg = Config()
    out = {'groups': catalog.GROUPS,
           'catalog': {n: catalog.info(n) for n in catalog.SECTIONS},
           'allow_changes': cfg.flag('general', 'allow_changes')}
    if what != 'cached':
        if what == 'all':
            names = list(catalog.SECTIONS)
        elif what in dict(catalog.GROUPS):
            names = catalog.sections_of(what)
        elif what in catalog.SECTIONS:
            names = [what]
        else:
            print(json.dumps({'status': 'error', 'message': 'unknown group or section %r' % what}))
            return 0
        if not (cfg.flag('switch', 'enabled') and cfg.get('switch', 'host')):
            print(json.dumps({'status': 'error', 'message': 'the switch is not configured'}))
            return 0
        try:
            data, errors = read_sections(cfg, names)
        except swlib.SwitchError as exc:
            print(json.dumps({'status': 'error', 'message': str(exc)}))
            return 0
        cache = merge(data, errors)
    else:
        cache = load_json('config.json', {})
    state = load_json('state.json', {})
    out.update({'status': 'ok', 'sections': cache.get('sections', {}), 'read_at': cache.get('read_at', {}),
                'errors': cache.get('errors', {}),
                'uplinks': sorted(p['name'] for p in (state.get('switch') or {}).get('ports', [])
                                  if p.get('role') == 'uplink')})
    print(json.dumps(out))
    return 0


if __name__ == '__main__':
    sys.exit(main())
