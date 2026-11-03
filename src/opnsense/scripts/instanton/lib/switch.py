"""
Client for the local web API of HPE Networking Instant On switches
(1930 / 1960 series running local management).

The switch web UI talks to an XML endpoint, ``/device/wcd?{Section}``.
Authentication is an RSA (PKCS#1 v1.5) encrypted credential string sent to
``<prefix>/config/system.xml?action=login`` which returns a ``sessionID``
cookie. Everything here is read-only: the client never issues a write
request to the switch.

Only the Python standard library is used so the script runs on a stock
OPNsense installation.
"""

import base64
import gzip
import http.cookiejar
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LOGIN_STATUS = {
    '0': 'ok',
    '1': 'username is missing',
    '4': 'invalid username or password',
    '5': 'too many users are logged in',
    '6': 'client configuration problem',
    '9': 'password expired',
    '10': 'ok (simple password)',
    '11': 'password does not meet complexity rules',
    '12': 'device password encryption problem',
    '13': 'ok (password about to expire)',
    '14': 'ok (initial setup completed)',
}
LOGIN_OK = ('0', '10', '13', '14')


class SwitchError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _der_read(data, pos):
    """Read one DER TLV, return (tag, value, next_pos)."""
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        count = length & 0x7f
        length = int.from_bytes(data[pos:pos + count], 'big')
        pos += count
    return tag, data[pos:pos + length], pos + length


def parse_rsa_public_key(pem_body):
    """Parse a PKCS#1 'RSA PUBLIC KEY' (or SPKI) body into (n, e)."""
    der = base64.b64decode(re.sub(r'-----[^-]+-----|\s', '', pem_body))
    tag, seq, _ = _der_read(der, 0)
    if tag != 0x30:
        raise SwitchError('unexpected RSA key format')
    tag, first, nxt = _der_read(seq, 0)
    if tag == 0x30:
        # SubjectPublicKeyInfo: AlgorithmIdentifier, BIT STRING(RSAPublicKey)
        tag, bits, _ = _der_read(seq, nxt)
        _, seq, _ = _der_read(bits[1:], 0)
        tag, first, nxt = _der_read(seq, 0)
    n = int.from_bytes(first, 'big')
    _, e_bytes, _ = _der_read(seq, nxt)
    return n, int.from_bytes(e_bytes, 'big')


def rsa_pkcs1_v15_encrypt(message, n, e):
    """RSAES-PKCS1-v1_5 encryption, hex encoded (as the switch UI does)."""
    k = (n.bit_length() + 7) // 8
    if len(message) > k - 11:
        raise SwitchError('credentials too long for RSA key')
    padding = b''
    while len(padding) < k - 3 - len(message):
        padding += bytes(b for b in os.urandom(k) if b != 0)
    padding = padding[:k - 3 - len(message)]
    block = b'\x00\x02' + padding + b'\x00' + message
    return format(pow(int.from_bytes(block, 'big'), e, n), 'x').zfill(k * 2)


def element_to_dict(elem):
    """Convert an XML element to plain dicts/lists.

    Leaf elements become strings; elements with repeated children become
    lists of dicts.
    """
    children = list(elem)
    if not children:
        return (elem.text or '').strip()
    out = {}
    for child in children:
        value = element_to_dict(child)
        if child.tag in out:
            if not isinstance(out[child.tag], list):
                out[child.tag] = [out[child.tag]]
            out[child.tag].append(value)
        else:
            out[child.tag] = value
    return out


def section_entries(section):
    """Return the list of row dicts of a table section, whatever the row tag."""
    if not isinstance(section, dict):
        return []
    rows = []
    for key, value in section.items():
        if isinstance(value, list):
            rows.extend(v for v in value if isinstance(v, dict))
        elif isinstance(value, dict) and any(not isinstance(v, (dict, list)) for v in value.values()):
            rows.append(value)
    return rows


class InstantOnSwitch:
    def __init__(self, host, username, password, verify_tls=False, timeout=20):
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.ctx = ssl.create_default_context()
        if not verify_tls:
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.cookies),
        )
        self.prefix = None
        self.logged_in = False

    # -- transport -------------------------------------------------------
    def _url(self, path):
        return 'https://%s%s' % (self.host, path)

    def _get(self, path):
        try:
            resp = self.opener.open(self._url(path), timeout=self.timeout)
            data = resp.read()
        except urllib.error.HTTPError as exc:
            raise SwitchError('HTTP %s on %s' % (exc.code, path.split('?')[0]))
        except (urllib.error.URLError, OSError) as exc:
            raise SwitchError('cannot reach %s: %s' % (self.host, getattr(exc, 'reason', exc)))
        if data[:2] == b'\x1f\x8b':
            data = gzip.decompress(data)
        return data.decode('utf-8', 'replace')

    def _discover_prefix(self):
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.ctx), _NoRedirect)
        try:
            opener.open(self._url('/'), timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get('Location', '')
            if '/config/' in location:
                return location.split('/config/')[0]
        except (urllib.error.URLError, OSError) as exc:
            raise SwitchError('cannot reach %s: %s' % (self.host, getattr(exc, 'reason', exc)))
        raise SwitchError('%s does not look like an Instant On switch in local management mode' % self.host)

    # -- session ---------------------------------------------------------
    def login(self):
        self.prefix = self._discover_prefix()
        enc = self._get('/device/wcd?{EncryptionSetting}')
        enabled = re.search(r'<passwEncryptEnable>(\d)</passwEncryptEnable>', enc)
        token = re.search(r'<loginToken>(.*?)</loginToken>', enc)
        token = token.group(1) if token else ''
        quote = lambda v: urllib.parse.quote(v, safe='')
        if enabled and enabled.group(1) == '1':
            key = re.search(r'<rsaPublicKey>(.*?)</rsaPublicKey>', enc, re.S)
            if not key:
                raise SwitchError('switch did not return an RSA public key')
            n, e = parse_rsa_public_key(key.group(1))
            plain = 'user=%s&password=%s&ssd=true&token=%s&' % (
                quote(self.username), quote(self.password), token)
            path = '%s/config/system.xml?action=login&cred=%s' % (
                self.prefix, rsa_pkcs1_v15_encrypt(plain.encode(), n, e))
        else:
            path = '%s/config/system.xml?action=login&user=%s&password=%s&ssd=true&' % (
                self.prefix, quote(self.username), quote(self.password))
        body = self._get(path)
        code = re.search(r'<statusCode>(\d*)</statusCode>', body)
        code = code.group(1) if code else ''
        if code not in LOGIN_OK:
            raise SwitchError('login failed: %s' % LOGIN_STATUS.get(code, 'status code %r' % code))
        self.logged_in = True
        return LOGIN_STATUS.get(code, code)

    def logout(self):
        if not self.logged_in:
            return
        try:
            self._get('/System.xml?action=logout')
        except SwitchError:
            pass
        self.logged_in = False

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *exc):
        self.logout()

    # -- data ------------------------------------------------------------
    def fetch(self, *sections):
        """Fetch one or more wcd sections in a single request.

        Returns {section_name: dict}. Sections the firmware does not know
        are simply missing from the result.
        """
        query = ''.join('{%s}' % s for s in sections)
        text = self._get('/device/wcd?' + query)
        if '<ResponseData' not in text:
            raise SwitchError('unexpected answer for %s' % ','.join(sections))
        try:
            root = ET.fromstring(text.encode('utf-8'))
        except ET.ParseError as exc:
            raise SwitchError('invalid XML for %s: %s' % (','.join(sections), exc))
        status = root.findtext('ActionStatus/statusCode') or ''
        if status not in ('', '0'):
            if status in ('4', '6') or 'login' in (root.findtext('ActionStatus/statusString') or '').lower():
                raise SwitchError('session rejected by the switch (status %s)' % status)
        result = {}
        config = root.find('DeviceConfiguration')
        if config is not None:
            for sec in config:
                if sec.tag != 'version':
                    result[sec.tag] = element_to_dict(sec)
        return result

    def fetch_many(self, sections, batch=4):
        out = {}
        failures = 0
        for i in range(0, len(sections), batch):
            chunk = sections[i:i + batch]
            try:
                out.update(self.fetch(*chunk))
            except SwitchError:
                # one unknown section can make a batch fail: retry one by one
                for single in chunk:
                    try:
                        out.update(self.fetch(single))
                    except SwitchError:
                        failures += 1
        if not out and failures:
            raise SwitchError('switch refused every request (session expired?)')
        return out
