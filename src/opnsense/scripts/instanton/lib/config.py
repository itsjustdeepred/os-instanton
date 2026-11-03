"""Configuration and on-disk locations."""

import configparser
import os

CONFIG_FILE = os.environ.get('INSTANTON_CONFIG', '/usr/local/etc/instanton/instanton.conf')
STATE_DIR = os.environ.get('INSTANTON_STATE_DIR', '/var/db/instanton')

DEFAULTS = {
    'general': {'enabled': '0', 'interval': '60', 'history_days': '14', 'event_limit': '2000',
                'flap_threshold': '5', 'poe_warn_percent': '80', 'clock_skew_seconds': '300'},
    'switch': {'enabled': '1', 'host': '', 'username': '', 'password': '', 'verify_tls': '0',
               'uplink_ports': '', 'log_entries': '200'},
    'aps': {'enabled': '1', 'discover': '1', 'hosts': '', 'port': '8080'},
    'cloud': {'enabled': '0', 'username': '', 'password': '', 'site': ''},
}


class Config:
    def __init__(self, path=CONFIG_FILE):
        self.path = path
        self.parser = configparser.RawConfigParser()
        for section, values in DEFAULTS.items():
            self.parser[section] = dict(values)
        self.loaded = bool(self.parser.read(path))
        if self.loaded:
            # the file holds passwords: keep it private even if it was
            # regenerated with default permissions
            try:
                if os.stat(path).st_mode & 0o077:
                    os.chmod(path, 0o600)
            except OSError:
                pass

    def get(self, section, key):
        return self.parser.get(section, key, fallback=DEFAULTS.get(section, {}).get(key, '')).strip()

    def flag(self, section, key):
        return self.get(section, key).lower() in ('1', 'yes', 'true', 'on')

    def int(self, section, key):
        try:
            return int(self.get(section, key))
        except ValueError:
            return int(DEFAULTS[section][key])

    def list(self, section, key):
        raw = self.get(section, key).replace(';', ',').replace(' ', ',')
        return [item for item in (part.strip() for part in raw.split(',')) if item]


def state_path(name):
    return os.path.join(STATE_DIR, name)
