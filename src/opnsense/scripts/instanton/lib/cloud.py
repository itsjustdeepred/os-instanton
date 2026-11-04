"""
Read-only client for the Instant On cloud portal API.

The API is undocumented. The flow below (portal settings -> SSO login ->
OAuth2 authorization code with PKCE -> bearer token) matches the one the
web portal uses and that several community integrations rely on. Accounts
with two-factor authentication enabled are not supported.

Only the Python standard library is used.
"""

import base64
import hashlib
import http.cookiejar
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

PORTAL_URL = 'https://portal.arubainstanton.com'
SSO_URL = 'https://sso.arubainstanton.com'
API_URL = 'https://nb.portal.arubainstanton.com/api'
API_VERSION = '7'


class CloudError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def pick(obj, *keys, default=''):
    for key in keys:
        value = obj.get(key)
        if value not in (None, ''):
            return value
    return default


class InstantOnCloud:
    def __init__(self, username, password, site=None, timeout=30):
        self.username = username
        self.password = password
        self.site = site
        self.timeout = timeout
        self.token = None
        self.token_expires = 0
        jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.noredir = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect)

    def _request(self, url, data=None, headers=None, opener=None):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers or {})
        try:
            with (opener or self.opener).open(req, timeout=self.timeout) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read() if hasattr(exc, 'read') else b''
        except (urllib.error.URLError, OSError) as exc:
            raise CloudError('cloud unreachable: %s' % getattr(exc, 'reason', exc))

    def login(self):
        status, _, body = self._request(PORTAL_URL + '/settings.json')
        if status != 200:
            raise CloudError('portal settings unavailable (HTTP %s)' % status)
        try:
            client_id = json.loads(body)['ssoClientIdAuthZ']
        except (ValueError, KeyError):
            raise CloudError('portal settings format changed')

        status, _, body = self._request(SSO_URL + '/aio/api/v1/mfa/validate/full',
                                        data={'username': self.username, 'password': self.password})
        if status in (401, 403):
            raise CloudError('invalid cloud credentials')
        try:
            session_token = json.loads(body).get('access_token')
        except ValueError:
            session_token = None
        if status != 200 or not session_token:
            raise CloudError('cloud login refused (HTTP %s); accounts with two-factor authentication '
                             'are not supported' % status)

        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        query = urllib.parse.urlencode({
            'client_id': client_id, 'redirect_uri': PORTAL_URL, 'response_type': 'code',
            'scope': 'profile openid', 'state': _b64url(secrets.token_bytes(24)),
            'code_challenge_method': 'S256', 'code_challenge': challenge, 'sessionToken': session_token,
        })
        status, headers, _ = self._request(SSO_URL + '/as/authorization.oauth2?' + query, opener=self.noredir)
        location = headers.get('Location') or headers.get('location') or ''
        code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get('code', [None])[0]
        if not code:
            raise CloudError('cloud authorization did not return a code')

        status, _, body = self._request(SSO_URL + '/as/token.oauth2', data={
            'client_id': client_id, 'redirect_uri': PORTAL_URL, 'code': code,
            'code_verifier': verifier, 'grant_type': 'authorization_code'})
        try:
            data = json.loads(body)
            self.token = data['access_token']
        except (ValueError, KeyError):
            raise CloudError('cloud token request failed (HTTP %s)' % status)
        self.token_expires = time.time() + max(30, int(data.get('expires_in', 300)) - 60)

    def get(self, path, optional=False):
        if not self.token or time.time() >= self.token_expires:
            self.login()
        headers = {'Authorization': 'Bearer ' + self.token, 'x-ion-api-version': API_VERSION,
                   'Accept': 'application/json'}
        status, _, body = self._request(API_URL + path, headers=headers)
        if status == 401:
            self.login()
            headers['Authorization'] = 'Bearer ' + self.token
            status, _, body = self._request(API_URL + path, headers=headers)
        if optional and status == 404:
            return None
        if status != 200:
            raise CloudError('API %s returned HTTP %s' % (path, status))
        try:
            return json.loads(body)
        except ValueError:
            raise CloudError('API %s returned invalid JSON' % path)

    def sites(self):
        return (self.get('/sites/') or {}).get('elements', [])

    def collect(self):
        sites = self.sites()
        if not sites:
            raise CloudError('the account has no Instant On sites')
        site = None
        if self.site:
            wanted = self.site.strip().lower()
            site = next((s for s in sites if wanted in (str(s.get('id', '')).lower(),
                                                        str(s.get('name', '')).lower())), None)
            if site is None:
                raise CloudError('site "%s" not found; available: %s' % (
                    self.site, ', '.join(str(s.get('name')) for s in sites)))
        else:
            site = sites[0]
        prefix = '/sites/%s' % site['id']
        inventory = (self.get(prefix + '/inventory') or {}).get('elements', [])
        clients = (self.get(prefix + '/clientSummary', optional=True) or {}).get('elements', [])
        networks = (self.get(prefix + '/networksSummary', optional=True) or {}).get('elements', [])
        alerts = (self.get(prefix + '/alertsSummary', optional=True) or {}).get('elements', [])
        return {
            'site': {'id': site.get('id'), 'name': site.get('name'), 'health': site.get('health', '')},
            'sites': [{'id': s.get('id'), 'name': s.get('name')} for s in sites],
            'devices': [normalize_device(d) for d in inventory],
            'clients': [normalize_client(c) for c in clients],
            # the API also returns the Wi-Fi passphrase (preSharedKey); it is never copied
            'networks': [{'name': pick(n, 'networkName', 'name', 'ssid'),
                          'type': pick(n, 'networkType', 'type'),
                          'enabled': n.get('isEnabled', n.get('enabled', '')),
                          'hidden': bool(n.get('isSsidHidden')),
                          'security': pick(n, 'security'), 'authentication': pick(n, 'authentication'),
                          'vlan': n.get('vlanId') if n.get('useVlan') else None,
                          'bands': [b for b, k in (('2.4 GHz', 'isAvailableOn24GHzRadioBand'),
                                                   ('5 GHz', 'isAvailableOn5GHzRadioBand'),
                                                   ('6 GHz', 'isAvailableOn6GHzRadioBand')) if n.get(k)],
                          'aps': len([a for a in n.get('accessPoints') or [] if a.get('isBoundToNetwork')]),
                          'clients': pick(n, 'clientsCount', 'wirelessClientsCount', default=0)}
                         for n in networks],
            'alerts': [{'type': pick(a, 'type', 'alertType'), 'severity': pick(a, 'severity'),
                        'time': pick(a, 'raisedTime', 'time'), 'device': pick(a, 'deviceName', 'source')}
                       for a in alerts],
        }


def normalize_device(d):
    radios = []
    for r in d.get('radios') or []:
        radios.append({'band': pick(r, 'band'), 'channel': pick(r, 'channel', 'channelNumber'),
                       'tx_power': r.get('txPowerEirpInDbm'), 'utilization': r.get('utilizationPercent'),
                       'clients': r.get('wirelessClientsCount')})
    return {
        'id': d.get('id'), 'name': pick(d, 'name'), 'model': pick(d, 'model'),
        'type': pick(d, 'deviceType'), 'serial': pick(d, 'serialNumber'),
        'mac': str(pick(d, 'macAddress')).lower(), 'ip': pick(d, 'ipAddress'),
        'firmware': pick(d, 'currentFirmwareVersion'), 'status': pick(d, 'status', 'operationalState'),
        'uptime': d.get('uptimeInSeconds'), 'up_to_date': d.get('isUpToDate'), 'radios': radios,
        'health': pick(d, 'health'),
        'problems': [pick(h, 'condition') for h in d.get('healthConditions') or [] if pick(h, 'condition')],
        # wireless mesh: the AP reaches the network through another AP
        'mesh_parent': pick(d, 'parentName') if d.get('parentId') else '',
        'mesh_snr': d.get('parentSnrInDb') if d.get('parentId') else None,
        'mesh_band': pick(d, 'parentRadioBand') if d.get('parentId') else '',
        'mesh_quality': pick(d.get('uplinkSummary') or {}, 'signalQuality') if d.get('parentId') else '',
        'locator_led': d.get('isLocatorLedActive'),
    }


def normalize_client(c):
    return {
        'id': c.get('id'), 'name': pick(c, 'name', 'hostName'),
        'mac': str(pick(c, 'macAddress', 'mac', 'id')).lower(), 'ip': pick(c, 'ipAddress'),
        'type': pick(c, 'clientType', default='wireless'),
        'ssid': pick(c, 'networkSsid', 'networkName', 'ssid', 'wirelessNetworkName'),
        'ap': pick(c, 'apName', 'accessPointName', 'deviceName'),
        'band': pick(c, 'wirelessBand', 'band', 'radioBand'),
        'protocol': pick(c, 'wirelessProtocol'), 'security': pick(c, 'wirelessSecurity'),
        'signal': c.get('signalInDbm'), 'snr': c.get('snrInDb'), 'signal_quality': pick(c, 'signalQuality'),
        'health': pick(c, 'health', 'healthInPercent'), 'network': pick(c, 'wiredNetworkName'),
        'blocked': bool(c.get('isBlocked')),
        'down_mbps': c.get('downstreamSpeedInMegabitsPerSecond'),
        'up_mbps': c.get('upstreamSpeedInMegabitsPerSecond'),
        'rx_bytes': c.get('upstreamDataTransferredInBytes'),
        'tx_bytes': c.get('downstreamDataTransferredInBytes'),
        'connected_s': c.get('connectionDurationInSeconds', c.get('stateDurationInSeconds')),
    }
