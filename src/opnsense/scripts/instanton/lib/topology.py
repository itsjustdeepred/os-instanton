"""
Network map: a tree from the firewall to switches, access points and clients.

Every node has one ``parent`` (the next hop towards the firewall) and a
``link`` describing that hop (switch port, speed, PoE, mesh signal).
Built from the state snapshot; nothing is read from the devices.
"""

from . import devicetype


def _speed(mbps):
    if not mbps:
        return ''
    return '%g Gb/s' % (mbps / 1000.0) if mbps >= 1000 else '%d Mb/s' % mbps


def _port_link(sw, port, multi):
    text = ('%s %s' % (sw.get('label', ''), port['name'])) if multi else port['name']
    return {'kind': 'wired', 'port': port['name'], 'switch': sw.get('id'), 'text': text,
            'speed': _speed(port.get('speed')), 'up': bool(port.get('up')),
            'poe_w': (port.get('poe') or {}).get('power_w') if (port.get('poe') or {}).get('status') == 'delivering'
            else None}


def build(state, switches):
    nodes = []
    multi = len(switches) > 1

    def add(node):
        nodes.append(node)
        return node

    add({'id': 'fw', 'parent': None, 'type': 'firewall', 'icon': 'shield',
         'label': state.get('hostname') or 'Firewall', 'sub': 'this firewall', 'online': True})

    # switches: walk the links between monitored switches outwards from the
    # switches that lead to the firewall
    by_id = {sw['id']: sw for sw in switches}
    links = {}  # switch id -> [(port on this switch, peer id)]
    for sw in switches:
        for p in sw.get('ports', []):
            if p.get('peer') in by_id and p['peer'] != sw['id']:
                links.setdefault(sw['id'], []).append((p, p['peer']))
    roots = [sw for sw in switches if any(p.get('role') == 'uplink' for p in sw.get('ports', []))]
    if not roots and switches:
        roots = [next((sw for sw in switches if sw.get('online')), switches[0])]
    parent_of, queue = {}, []
    for sw in roots:
        if sw['id'] not in parent_of:
            parent_of[sw['id']] = None
            queue.append(sw['id'])
    while queue:
        current = queue.pop(0)
        for port, peer in links.get(current, []):
            if peer not in parent_of:
                parent_of[peer] = (by_id[current], port)
                queue.append(peer)
    for sw in switches:
        up = parent_of.get(sw['id'])
        uplink = next((p for p in sw.get('ports', []) if p.get('role') == 'uplink'), None)
        if up:
            link = _port_link(up[0], up[1], multi)
        elif uplink:
            link = dict(_port_link(sw, uplink, False), text='port ' + uplink['name'])
        else:
            link = {'kind': 'unknown', 'text': 'uplink not detected'}
        add({'id': 'sw:' + sw['id'], 'parent': 'sw:' + up[0]['id'] if up else 'fw', 'type': 'switch',
             'icon': 'sitemap', 'label': sw.get('label') or sw.get('host'), 'online': bool(sw.get('online')),
             'sub': ' · '.join(x for x in (sw.get('model', ''), sw.get('host', '')) if x),
             'href': '/ui/instanton/index/switch#sw=' + sw['id'], 'link': link})

    # other switches announced through LLDP but not monitored
    lldp_nodes = {}
    for sw in switches:
        for p in sw.get('ports', []):
            n = p.get('neighbor') or {}
            if p.get('role') == 'switch' and not p.get('peer') and n:
                nid = 'lldp:%s:%s' % (sw['id'], p['name'])
                lldp_nodes[(sw['id'], p['name'])] = nid
                add({'id': nid, 'parent': 'sw:' + sw['id'], 'type': 'switch', 'icon': 'sitemap',
                     'label': n.get('name') or n.get('chassis_id') or 'switch', 'sub': n.get('ip', ''),
                     'online': bool(p.get('up')), 'unmanaged': True, 'link': _port_link(sw, p, False)})

    # access points: wired ones on their switch port, meshed ones under their parent AP
    cloud = state.get('cloud') or {}
    cloud_devs = {d.get('mac'): d for d in cloud.get('devices', []) if d.get('mac')}
    ap_ids = {}
    for a in state.get('aps', []):
        key = a.get('mac') or a.get('host')
        ap_ids[a['name']] = 'ap:' + key
        if a.get('mac'):
            ap_ids[a['mac']] = 'ap:' + key
    seen_ap = set()
    pending_mesh = []
    for a in state.get('aps', []):
        nid = ap_ids[a['name']]
        sw = by_id.get(a.get('switch'))
        port = next((p for p in (sw or {}).get('ports', []) if p['name'] == a.get('port')), None)
        cd = cloud_devs.get(a.get('mac')) or {}
        node = {'id': nid, 'type': 'ap', 'icon': 'wifi', 'label': a['name'], 'online': bool(a.get('online')),
                'sub': ' · '.join(x for x in (a.get('model', ''), a.get('host', '')) if x),
                'href': '/ui/instanton/index/accesspoints', 'clients': a.get('clients')}
        if sw and port:
            node.update(parent='sw:' + sw['id'], link=_port_link(sw, port, multi))
        elif cd.get('mesh_parent_id'):
            node['mesh_parent'] = cd['mesh_parent_id']
            node['link'] = {'kind': 'mesh', 'text': 'mesh %s' % (cd.get('mesh_band') or ''),
                            'snr': cd.get('mesh_snr'), 'quality': cd.get('mesh_quality')}
            pending_mesh.append(node)
        else:
            node.update(parent='fw', link={'kind': 'unknown', 'text': 'not on a monitored switch'})
        add(node)
        seen_ap.add(a.get('mac'))
    # access points known only to the cloud
    for mac, d in cloud_devs.items():
        if mac in seen_ap or d.get('type') not in ('accessPoint', 'ap'):
            continue
        nid = 'ap:' + mac
        ap_ids[d.get('name')] = nid
        ap_ids[mac] = nid
        node = add({'id': nid, 'type': 'ap', 'icon': 'wifi', 'label': d.get('name') or mac,
                    'online': d.get('status') == 'up', 'sub': ' · '.join(x for x in (d.get('model', ''), d.get('ip', ''))
                                                                         if x),
                    'href': '/ui/instanton/index/accesspoints', 'site': d.get('site')})
        if d.get('mesh_parent_id'):
            node['mesh_parent'] = d['mesh_parent_id']
            node['link'] = {'kind': 'mesh', 'text': 'mesh %s' % (d.get('mesh_band') or ''),
                            'snr': d.get('mesh_snr'), 'quality': d.get('mesh_quality')}
            pending_mesh.append(node)
        else:
            node.update(parent='fw', link={'kind': 'unknown', 'text': 'cloud only'})
    for node in pending_mesh:
        node['parent'] = ap_ids.get(node.pop('mesh_parent'), 'fw')

    # clients
    for c in state.get('clients', []):
        if not c.get('online'):
            continue
        parent = None
        if c.get('connection') == 'wireless' and c.get('ap'):
            parent = ap_ids.get(c['ap'])
            link = {'kind': 'wireless', 'text': ' '.join(x for x in (c.get('ssid') or '', c.get('band') or '') if x),
                    'snr': c.get('snr'), 'quality': c.get('signal_quality')}
        if not parent and c.get('switch') in by_id:
            sw = by_id[c['switch']]
            port = next((p for p in sw.get('ports', []) if p['name'] == c.get('port')), None)
            parent = lldp_nodes.get((sw['id'], c.get('port'))) or 'sw:' + sw['id']
            link = _port_link(sw, port, False) if port else {'kind': 'wired', 'text': c.get('port', '')}
        if not parent:
            parent = 'fw'
            link = {'kind': 'unknown', 'text': ''}
        kind = c.get('type') or 'unknown'
        add({'id': 'c:' + c['mac'], 'parent': parent, 'type': kind,
             'icon': c.get('type_icon') or devicetype.TYPES.get(kind, devicetype.TYPES['unknown'])[1],
             'type_label': c.get('type_label') or devicetype.TYPES.get(kind, devicetype.TYPES['unknown'])[0],
             'label': c.get('description') or c.get('hostname') or c.get('port_label') or c['mac'],
             'sub': ' · '.join(x for x in (c.get('ip', ''), c.get('vendor', '') if not c.get('random_mac') else '') if x),
             'mac': c['mac'], 'online': True, 'client': True, 'link': link,
             'href': '/ui/instanton/index/clients#mac=' + c['mac']})
    return {'nodes': nodes, 'types': {k: {'label': v[0], 'icon': v[1]} for k, v in devicetype.TYPES.items()}}
