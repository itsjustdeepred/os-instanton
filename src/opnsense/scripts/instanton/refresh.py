#!/usr/local/bin/python3
"""
Refresh the data now. When the monitor daemon runs it is asked to poll
(SIGUSR1, keeps its switch session); otherwise one poll runs inline.
"""

import json
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import state_path  # noqa: E402

PIDFILE = os.environ.get('INSTANTON_PIDFILE', '/var/run/instanton.pid')


def daemon_pid():
    try:
        pid = int(open(PIDFILE).read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def main():
    pid = daemon_pid()
    if pid:
        try:
            before = os.path.getmtime(state_path('state.json'))
        except OSError:
            before = 0
        os.kill(pid, signal.SIGUSR1)
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                if os.path.getmtime(state_path('state.json')) > before:
                    print(json.dumps({'status': 'ok', 'via': 'daemon'}))
                    return 0
            except OSError:
                pass
        print(json.dumps({'status': 'timeout', 'via': 'daemon'}))
        return 0
    here = os.path.dirname(os.path.abspath(__file__))
    out = subprocess.run([sys.executable, os.path.join(here, 'collect.py')], capture_output=True, text=True)
    print(out.stdout.strip() or json.dumps({'status': 'error', 'message': out.stderr.strip()[-500:]}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
