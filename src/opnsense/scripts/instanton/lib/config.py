"""Configuration and on-disk locations.

The configuration file holds global sections ([general], [aps]) and one
section per device or account: ``[switch:<id>]`` for every switch and
``[cloud:<id>]`` for every Instant On cloud account. A single legacy
``[switch]`` / ``[cloud]`` section is still accepted and gets the id
``default``.
"""

import configparser
import os
import re

CONFIG_FILE = os.environ.get('INSTANTON_CONFIG', '/usr/local/etc/instanton/instanton.conf')
STATE_DIR = os.environ.get('INSTANTON_STATE_DIR', '/var/db/instanton')

DEFAULTS = {
    'general': {'enabled': '0', 'interval': '60', 'history_days': '14', 'event_limit': '2000',
                'flap_threshold': '5', 'poe_warn_percent': '80', 'clock_skew_seconds': '300',
                'allow_changes': '0', 'log_entries': '200'},
    'aps': {'enabled': '1', 'discover': '1', 'hosts': '', 'port': '8080'},
}
DEVICE_DEFAULTS = {
    'switch': {'enabled': '1', 'name': '', 'host': '', 'username': '', 'password': '', 'verify_tls': '0',
               'uplink_ports': '', 'save_after_change': '1'},
    'cloud': {'enabled': '1', 'name': '', 'username': '', 'password': '', 'sites': '', 'site': ''},
}
ID_RE = re.compile(r'^[A-Za-z0-9-]{1,64}$')


def _truthy(value):
    return str(value).strip().lower() in ('1', 'yes', 'true', 'on')


def _split(value):
    raw = str(value).replace(';', ',').replace('\n', ',')
    return [item for item in (part.strip() for part in raw.split(',')) if item]


class Device:
    """One switch or cloud account: ``id`` plus its settings."""

    def __init__(self, kind, ident, values):
        self.kind = kind
        self.id = ident
        self.values = dict(DEVICE_DEFAULTS[kind], **values)

    def get(self, key):
        return str(self.values.get(key, '')).strip()

    def flag(self, key):
        return _truthy(self.get(key))

    def list(self, key):
        """Comma separated list; site names may contain spaces, port lists may not."""
        value = self.get(key)
        return _split(value if key == 'sites' else value.replace(' ', ','))

    @property
    def label(self):
        return self.get('name') or self.get('host') or self.get('username') or self.id

    @property
    def usable(self):
        if self.kind == 'switch':
            return self.flag('enabled') and bool(self.get('host'))
        return self.flag('enabled') and bool(self.get('username'))

    def __repr__(self):
        return '<%s %s>' % (self.kind, self.id)


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
        return _truthy(self.get(section, key))

    def int(self, section, key):
        try:
            return int(self.get(section, key))
        except ValueError:
            return int(DEFAULTS[section][key])

    def list(self, section, key):
        return _split(self.get(section, key).replace(' ', ','))

    def devices(self, kind):
        """Every configured switch or cloud account, enabled or not, in file order."""
        out = []
        for section in self.parser.sections():
            if section == kind:
                values = dict(self.parser.items(section))
                if values.get('host') or values.get('username'):
                    if kind == 'cloud' and values.get('site') and not values.get('sites'):
                        values['sites'] = values['site']
                    out.append(Device(kind, 'default', values))
            elif section.startswith(kind + ':'):
                ident = section.split(':', 1)[1]
                if ID_RE.match(ident):
                    out.append(Device(kind, ident, dict(self.parser.items(section))))
        return out

    def switches(self, usable_only=True):
        return [d for d in self.devices('switch') if d.usable or not usable_only]

    def clouds(self, usable_only=True):
        return [d for d in self.devices('cloud') if d.usable or not usable_only]

    def switch(self, ident=None):
        """The usable switch with this id; without an id the only usable switch."""
        switches = self.switches()
        if ident:
            return next((d for d in switches if d.id == ident), None)
        return switches[0] if len(switches) == 1 else None


def state_path(name):
    return os.path.join(STATE_DIR, name)
