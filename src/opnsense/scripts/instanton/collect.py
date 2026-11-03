#!/usr/local/bin/python3
"""
Poll the Instant On devices once (--once, default) or forever (--loop).
"""

import argparse
import os
import signal
import sys
import syslog
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import collector  # noqa: E402
from lib.config import Config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description='Instant On collector')
    parser.add_argument('--loop', action='store_true', help='keep polling at the configured interval')
    parser.add_argument('--quiet', action='store_true', help='do not print the summary')
    args = parser.parse_args()
    if not args.loop:
        state = collector.run(Config())
        if not args.quiet:
            import json
            print(json.dumps({'status': 'ok', 'summary': state['summary'], 'sources': state['sources'],
                              'duration_ms': state['duration_ms']}))
        return 0
    collector.log(syslog.LOG_NOTICE, 'monitor started')

    def stop(signum, frame):
        collector.close_sessions()
        collector.log(syslog.LOG_NOTICE, 'monitor stopped')
        sys.exit(0)

    class PollNow(Exception):
        pass

    def poll_now(signum, frame):
        raise PollNow()

    signal.signal(signal.SIGUSR1, poll_now)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while True:
        cfg = Config()
        interval = max(15, cfg.int('general', 'interval'))
        started = time.time()
        try:
            collector.run(cfg, persistent=True)
        except PollNow:
            continue
        except Exception:  # keep the daemon alive, report the failure
            collector.log(syslog.LOG_ERR, 'poll crashed: %s' % traceback.format_exc().replace('\n', ' | '))
        try:
            time.sleep(max(5, interval - (time.time() - started)))
        except PollNow:
            pass


if __name__ == '__main__':
    sys.exit(main())
