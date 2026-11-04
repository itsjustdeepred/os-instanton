"""
Guess what kind of device a MAC address belongs to.

Signals, strongest first:

1. the name: firewall static mapping description, DHCP host name, switch port
   description, cloud client name (device names often say what they are);
2. the fingerprint of the Instant On cloud (e.g. ["Brother", "Printer"]);
3. LLDP: access points, switches and phones announce themselves;
4. the manufacturer registered for the first half of the MAC address (OUI).

Name patterns include common words in a few European languages because
people name devices in their own language.
"""

import re

# type -> (label, Font Awesome icon)
TYPES = {
    'router': ('Router / gateway', 'globe'),
    'firewall': ('Firewall', 'shield'),
    'switch': ('Switch', 'sitemap'),
    'ap': ('Access point', 'wifi'),
    'network': ('Network device', 'random'),
    'server': ('Server', 'server'),
    'vm': ('Virtual machine', 'cubes'),
    'nas': ('NAS / storage', 'hdd-o'),
    'computer': ('Computer', 'desktop'),
    'laptop': ('Laptop', 'laptop'),
    'phone': ('Phone', 'mobile'),
    'tablet': ('Tablet', 'tablet'),
    'watch': ('Watch', 'clock-o'),
    'tv': ('TV', 'television'),
    'media': ('Media player', 'play-circle'),
    'speaker': ('Speaker', 'volume-up'),
    'console': ('Game console', 'gamepad'),
    'printer': ('Printer', 'print'),
    'camera': ('Camera', 'video-camera'),
    'nvr': ('Video recorder', 'film'),
    'intercom': ('Intercom / doorbell', 'bell'),
    'alarm': ('Alarm system', 'lock'),
    'voip': ('VoIP phone', 'phone'),
    'iot': ('Smart home', 'lightbulb-o'),
    'climate': ('Climate / heating', 'thermometer-half'),
    'appliance': ('Appliance', 'cutlery'),
    'ev': ('EV charger', 'car'),
    'power': ('UPS / power', 'battery-full'),
    'unknown': ('Unknown', 'question'),
}

# (type, pattern) checked against the device names in this order: the more
# specific kinds come first ("Shelly-Washer" is a smart relay, not a washer).
NAME_RULES = [
    ('intercom', r'intercom|citofono|videocitofono|interphone|door ?station|doorbell|campanello|sprechanlage'),
    ('nvr', r'\bnvr\b|\bdvr\b|recorder|videoregistratore'),
    ('camera', r'\bcam\b|camera|telecamera|\bipcam|webcam|kamera|cam\d|\btapo c\d+|^c(100|110|200|210|220|310|320|500)$'),
    ('alarm', r'alarm|allarme|centrale|alarmanlage'),
    ('iot', r'shelly|sonoff|tasmota|esphome|\besp(32|8266)?\b|tuya|\bkasa\b|tapo p\d+|smart ?plug'),
    ('printer', r'print|stampante|drucker|imprimante|laserjet|officejet|deskjet|\bbrw|\bepson|bambu|prusa|\bmfc'),
    ('nas', r'\bnas\b|synology|diskstation|qnap|truenas|readynas'),
    ('server', r'server|proxmox|\bpve\b|esxi|jellyfin|plex|home ?assistant|hassio|unraid|docker|\bnuc\b'),
    ('vm', r'\bvm\b|virtual'),
    ('tablet', r'ipad|\btab\b|tablet|galaxy ?tab|kindle|fire ?hd'),
    ('watch', r'watch|orologio'),
    ('phone', r'iphone|android|galaxy|pixel|redmi|oneplus|xiaomi|\bs\d{2}\b|ultra|phone|telefono|cellulare|handy'),
    ('laptop', r'macbook|laptop|notebook|thinkpad|ideapad|\bxps\b|surface|chromebook'),
    ('tv', r'\btv\b|televisio|televisore|fernseher|bravia|webos|tizen|smart ?tv'),
    ('media', r'chromecast|apple ?tv|\broku\b|fire ?tv|shield|media ?player|kodi|appletv'),
    ('speaker', r'sonos|\bzp\b|sonoszp|echo|alexa|homepod|google ?home|nest ?(mini|audio|hub)|speaker|soundbar|cassa'),
    ('console', r'playstation|\bps[345]\b|xbox|nintendo'),
    ('voip', r'voip|\bsip\b|yealink|snom|gigaset|grandstream|polycom'),
    ('ev', r'wallbox|charger|easee|zaptec|wallbox|colonnina|ladestation'),
    ('climate', r'air ?condition|climat|condizionat|thermostat|termostato|heat ?pump|pompa di calore|caldaia|boiler|'
                r'daikin|tado|netatmo|\bhvac\b'),
    ('appliance', r'fridge|frigo|refrigerator|lavatrice|washer|washing|dryer|asciugatrice|dishwasher|lavastoviglie|'
                  r'oven|forno|cooktop|induction|piano cottura|\bhood\b|cappa|microwave|coffee|caffe|miele|\bneff\b|'
                  r'bosch|siemens|robot|roborock|roomba|vacuum|aspirapolvere|purifier'),
    ('power', r'\bups\b|\bpdu\b|inverter|solar|fotovoltaico'),
    ('iot', r'sensor|sensore|presence|motion|\bplug\b|presa|relay|rele|zigbee|z-?wave|gateway|bridge|\bhue\b|'
            r'\bled\b|lamp|lampada|\bluce\b|light|weather|meteo|domotic|smart|vimar|bticino|irrigat|garage|gate|cancello'),
    ('firewall', r'opnsense|pfsense|firewall'),
    ('router', r'router|fritz|modem|\bont\b|gateway'),
    ('ap', r'access ?point|\bap\b'),
    ('switch', r'\bswitch\b'),
    ('network', r'mesh|repeater|extender|ripetitore'),
    ('computer', r'imac|desktop|\bpc\b|workstation|computer|mac ?mini|mac ?studio|raspberry|\brpi\b'),
]

# (type, manufacturer pattern); manufacturers that make many kinds of devices
# (Apple, Samsung, LG, Huawei, Xiaomi, Amazon, Google) are left out.
VENDOR_RULES = [
    ('camera', r'hikvision|dahua|axis communications|hanwha|uniview|reolink|amcrest|foscam|ezviz|imou|mobotix|vivotek'),
    ('nas', r'synology|qnap|western digital|asustor|terramaster|buffalo'),
    ('speaker', r'sonos|bose|denon|bang & olufsen|harman|bluesound|marantz'),
    ('iot', r'espressif|shelly|allterco|tuya|lumi united|aqara|itead|signify|philips lighting|lifx|nanoleaf|'
            r'ecobee|netatmo|weatherflow|laird|vimar|bticino|legrand|silicon labs|nordic semiconductor|'
            r'texas instruments|murata|azurewave|seongji|sji industry|chongqing fugui|meross|wiz connected|'
            r'wistron neweb|universal global scientific|hui zhou gaoshengda'),
    ('climate', r'daikin|tado|mitsubishi electric|gree electric|midea|viessmann|vaillant'),
    ('appliance', r'miele|bsh hausger|electrolux|whirlpool|haier|candy|smeg|liebherr|irobot|roborock|dreame|ecovacs'),
    ('printer', r'brother|canon|seiko epson|lexmark|kyocera|ricoh|xerox|konica|zebra|bambu'),
    ('vm', r'proxmox|vmware|qemu|xensource|parallels'),
    ('computer', r'intel corporate|elitegroup|giga-byte|asustek|micro-star|asrock|dell|lenovo|wistron corp|quanta|'
                 r'compal|liteon|raspberry pi|pegatron|super micro'),
    ('alarm', r'tecnoalarm|ajax systems|paradox|bentel|inim|risco|digital security controls|honeywell security'),
    ('intercom', r'2n telecom|fermax|comelit|urmet|doorbird|akuvox'),
    ('voip', r'yealink|snom|polycom|grandstream|gigaset|fanvil|avaya|mitel'),
    ('console', r'nintendo|sony interactive|valve'),
    ('media', r'roku|nvidia'),
    ('ev', r'wallbox|easee|zaptec|tesla|enphase|alfen'),
    ('power', r'american power conversion|schneider|eaton|delta electronics|cyber power|riello|vertiv|sma solar|'
              r'fronius|huawei digital power|solaredge'),
    ('firewall', r'deciso|netgate|fortinet|sophos|watchguard|palo alto'),
    ('network', r'ubiquiti|mikrotik|tp-link|netgear|cisco|juniper|aruba|hewlett packard enterprise|zyxel|d-link|'
                r'linksys|avm gmbh|draytek|cambium|ruckus|edgecore|tenda|mercusys|eero|plume'),
]

# fingerprints of the Instant On cloud
CLOUD_TYPES = {
    'iot': 'iot', 'printer': 'printer', 'router': 'router', 'android': 'phone', 'ios': 'phone', 'iphone': 'phone',
    'ipad': 'tablet', 'windows': 'computer', 'macos': 'computer', 'mac os': 'computer', 'linux': 'computer',
    'chrome os': 'laptop', 'camera': 'camera', 'ip camera': 'camera', 'tv': 'tv', 'smart tv': 'tv',
    'gaming': 'console', 'game console': 'console', 'voip': 'voip', 'ip phone': 'voip', 'nas': 'nas',
    'storage': 'nas', 'access point': 'ap', 'switch': 'switch', 'media': 'media', 'speaker': 'speaker',
    'watch': 'watch', 'tablet': 'tablet', 'phone': 'phone', 'smartphone': 'phone', 'laptop': 'laptop',
    'computer': 'computer', 'server': 'server',
}

_NAME_RES = [(t, re.compile(p)) for t, p in NAME_RULES]
_VENDOR_RES = [(t, re.compile(p, re.I)) for t, p in VENDOR_RULES]


def _norm(text):
    return re.sub(r'[-_.]+', ' ', str(text or '').lower()).strip()


def from_name(*names):
    for raw in names:
        text = _norm(raw)
        if not text or re.match(r'^([0-9a-f]{2} ?){6}$', text):  # a MAC address is not a name
            continue
        for kind, rx in _NAME_RES:
            if rx.search(text):
                return kind
    return None


def from_vendor(vendor):
    if not vendor:
        return None
    for kind, rx in _VENDOR_RES:
        if rx.search(vendor):
            return kind
    return None


def from_cloud(classification):
    for item in classification or []:
        kind = CLOUD_TYPES.get(str(item).strip().lower())
        if kind:
            return kind
    return None


def from_lldp(neighbor):
    if not neighbor:
        return None
    if neighbor.get('is_ap'):
        return 'ap'
    caps = neighbor.get('capabilities') or ''
    # LLDP system capabilities bit string: other, repeater, bridge, WLAN AP, router, telephone, ...
    if caps[3:4] == '1':
        return 'ap'
    if caps[5:6] == '1':
        return 'voip'
    if caps[4:5] == '1':
        return 'router'
    if caps[2:3] == '1':
        return 'switch'
    return None


def classify(names=(), vendor='', classification=None, neighbor=None):
    """Return {'type', 'type_label', 'type_icon', 'type_source'}."""
    for source, kind in (('name', from_name(*names)), ('cloud', from_cloud(classification)),
                         ('lldp', from_lldp(neighbor)), ('vendor', from_vendor(vendor))):
        if kind:
            break
    else:
        source, kind = '', 'unknown'
    label, icon = TYPES[kind]
    return {'type': kind, 'type_label': label, 'type_icon': icon, 'type_source': source}
