#!/usr/local/bin/python3
"""
List the Instant On sites of one cloud account, for the site selection in
the settings.

usage: cloudsites.py <account id>
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import cloud as cloudlib  # noqa: E402
from lib.config import Config  # noqa: E402


def main():
    ident = sys.argv[1] if len(sys.argv) > 1 else ''
    if not re.match(r'^[A-Za-z0-9-]{1,64}$', ident):
        print(json.dumps({'status': 'error', 'message': 'invalid account id'}))
        return 0
    acc = next((a for a in Config().clouds(usable_only=False) if a.id == ident), None)
    if acc is None or not acc.get('username'):
        print(json.dumps({'status': 'error', 'message': 'save the account and press Apply first'}))
        return 0
    try:
        sites = cloudlib.InstantOnCloud(acc.get('username'), acc.get('password')).sites()
    except cloudlib.CloudError as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}))
        return 0
    wanted = {w.lower() for w in acc.list('sites')}
    print(json.dumps({'status': 'ok', 'sites': [
        {'id': s.get('id'), 'name': s.get('name'), 'health': s.get('health', ''), 'status': s.get('status', ''),
         'role': s.get('userRoleOnSite', ''),
         'selected': not wanted or str(s.get('id', '')).lower() in wanted or str(s.get('name', '')).lower() in wanted}
        for s in sites]}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
