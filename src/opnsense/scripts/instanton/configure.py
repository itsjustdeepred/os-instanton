#!/usr/local/bin/python3
"""
Apply one configuration change to the switch.

usage: configure.py <base64url JSON {"action": ..., "params": {...}}>

Changes are refused unless "Allow changes" is enabled in the settings.
The result is printed as JSON; the change is written to the event history
and to syslog, and the monitor is asked to poll again so the pages show the
new state.
"""

import base64
import json
import os
import signal
import sys
import syslog
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import actions  # noqa: E402
from lib import catalog  # noqa: E402
from lib import switch as swlib  # noqa: E402
from lib.collector import load_json, log, save_json  # noqa: E402
from lib.config import Config  # noqa: E402

PIDFILE = os.environ.get('INSTANTON_PIDFILE', '/var/run/instanton.pid')


def decode(arg):
    try:
        data = json.loads(base64.urlsafe_b64decode(arg + '=' * (-len(arg) % 4)).decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise actions.ActionError('malformed request')
    if not isinstance(data, dict) or not isinstance(data.get('params', {}), dict):
        raise actions.ActionError('malformed request')
    return data.get('action'), data.get('params') or {}


def record(cfg, level, message):
    events = load_json('events.json', [])
    events.append({'time': time.time(), 'level': level, 'area': 'change', 'message': message})
    save_json('events.json', events[-cfg.int('general', 'event_limit'):])
    log(syslog.LOG_NOTICE if level == 'info' else syslog.LOG_ERR, '[change] %s' % message)


def poke_monitor():
    try:
        os.kill(int(open(PIDFILE).read().strip()), signal.SIGUSR1)
        return True
    except (OSError, ValueError):
        return False


def main():
    cfg = Config()
    try:
        if len(sys.argv) < 2:
            raise actions.ActionError('no request')
        action, params = decode(sys.argv[1])
        if not cfg.flag('general', 'allow_changes'):
            raise actions.ActionError('changes are disabled; enable "Allow changes" in Services > Instant On > Settings')
        if not (cfg.flag('switch', 'enabled') and cfg.get('switch', 'host')):
            raise actions.ActionError('the switch is not configured')
        state = load_json('state.json', {})
        config = load_json('config.json', {})
        changes, _ = actions.plan(action, params, state, config)  # validate before logging in
        client = swlib.InstantOnSwitch(cfg.get('switch', 'host'), cfg.get('switch', 'username'),
                                       cfg.get('switch', 'password'), verify_tls=cfg.flag('switch', 'verify_tls'))
        client.login()
        try:
            result = actions.execute(client, action, params, state, save=cfg.flag('switch', 'save_after_change'),
                                     config=config)
            # keep the editor's copy of the changed sections current
            touched = [s for s in dict.fromkeys(c[0] for c in changes) if s in catalog.SECTIONS]
            if touched and client.logged_in:
                try:
                    fresh = {}
                    for name in touched:
                        fresh.update(client.fetch(name))
                    cache = load_json('config.json', {})
                    cache.setdefault('sections', {}).update(fresh)
                    cache.setdefault('read_at', {}).update({n: time.time() for n in fresh})
                    save_json('config.json', cache)
                except swlib.SwitchError:
                    pass
        finally:
            client.logout()
    except (actions.ActionError, swlib.SwitchError) as exc:
        message = str(exc)
        if isinstance(exc, swlib.SwitchError):
            record(cfg, 'error', 'Change refused by the switch: %s' % message)
        print(json.dumps({'status': 'error', 'message': message}))
        return 0
    record(cfg, 'info', result['message'] + (' (not saved to startup configuration)' if result['saved'] is False else ''))
    result['refresh'] = 'monitor' if poke_monitor() else 'manual'
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
