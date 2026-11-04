"""
Catalogue of the switch configuration sections that the web interface of
Instant On 1930/1960 switches can change, as used by the generic
configuration editor.

Risk levels:

* ``normal``  – applied directly.
* ``caution`` – can interrupt traffic (loops, filtering, link resets);
  the request must carry an explicit confirmation.
* ``blocked`` – management access, accounts, authentication, certificates,
  firmware and access lists: a mistake can lock the firewall out of the
  switch, so the plugin shows these sections read-only.

Each entry: (group, kind, risk, row tag, title). ``kind`` is ``setting``
(one set of values) or ``table`` (a list of rows); ``row tag`` is the
element name of a table row.
"""

GROUPS = [
    ('system', 'System'),
    ('ports', 'Ports and PoE'),
    ('vlan', 'VLANs'),
    ('stp', 'Spanning tree and loops'),
    ('mcast', 'Multicast'),
    ('qos', 'Quality of service'),
    ('security', 'Security'),
    ('ip', 'IP services'),
    ('monitor', 'Logging and monitoring'),
    ('mgmt', 'Management access'),
]

N, C, B = 'normal', 'caution', 'blocked'

SECTIONS = {
    # system
    'SystemGlobalSetting': ('system', 'setting', N, None, 'System name, location and contact'),
    'TimeSetting': ('system', 'setting', N, None, 'Clock, time zone and daylight saving'),
    'SNTPGlobalSetting': ('system', 'setting', N, None, 'SNTP client'),
    'SNTPServerTable': ('system', 'table', N, 'SNTPServerEntry', 'SNTP servers'),
    'LocateUnit': ('system', 'setting', N, None, 'Locator LED'),
    'GreenEthGlobalSetting': ('system', 'setting', N, None, 'Energy saving (Green Ethernet)'),
    'EEEGlobalSetting': ('system', 'setting', N, None, 'Energy Efficient Ethernet'),
    'UnexpectedRestart': ('system', 'setting', N, None, 'Unexpected restart flag'),
    'TimeRangeList': ('system', 'table', N, 'Entry', 'Time ranges'),
    'TimeRangePeriodicList': ('system', 'table', N, 'Entry', 'Periodic time ranges'),
    'GlobalStatisticsSetting': ('system', 'setting', N, None, 'Statistics settings'),
    # ports
    'Standard802_3List': ('ports', 'table', C, 'Entry', 'Port settings (state, speed, description)'),
    'InterfaceGlobalSetting': ('ports', 'setting', C, None, 'Global port settings'),
    'PoEPSEInterfaceList': ('ports', 'table', N, 'Interface', 'PoE per port'),
    'PoEPSEUnitList': ('ports', 'table', N, 'Entry', 'PoE power budget'),
    'EEEInterfaceList': ('ports', 'table', N, 'Entry', 'Energy Efficient Ethernet per port'),
    'LACPGlobalSetting': ('ports', 'setting', C, None, 'LACP'),
    'LAGList': ('ports', 'table', C, 'Entry', 'Link aggregation groups'),
    'LACPPortList': ('ports', 'table', C, 'Entry', 'LACP per port'),
    'StormControlTable': ('ports', 'table', C, 'Entry', 'Storm control'),
    'ErrorRecoveryTable': ('ports', 'table', N, 'Entry', 'Automatic error recovery'),
    'InterfaceRecoveryGlobalSetting': ('ports', 'setting', N, None, 'Error recovery interval'),
    'TimeBasedPortTable': ('ports', 'table', C, 'Entry', 'Port schedules'),
    'CableTestPortList': ('ports', 'table', C, 'Entry', 'Cable test'),
    'SpanSourceTable': ('ports', 'table', C, 'Entry', 'Port mirroring sources'),
    'SpanDestinationTable': ('ports', 'table', C, 'Entry', 'Port mirroring destination'),
    'ForwardingGlobalSetting': ('ports', 'setting', N, None, 'MAC address aging'),
    'ForwardingStaticTable': ('ports', 'table', C, 'Entry', 'Static MAC addresses'),
    'PseCountersClear': ('ports', 'setting', N, None, 'Clear PoE counters'),
    'InterfaceQueueStatisticsClear': ('ports', 'setting', N, None, 'Clear queue counters'),
    # VLANs
    'VLANGlobalSetting': ('vlan', 'setting', C, None, 'VLAN settings'),
    'VLANList': ('vlan', 'table', C, 'VLAN', 'VLANs'),
    'VLANInterfaceList': ('vlan', 'table', C, 'Entry', 'Port VLAN mode'),
    'VLANInterfaceISList': ('vlan', 'table', C, 'Entry', 'Port VLAN membership'),
    'VoiceVLANGlobalSetting': ('vlan', 'setting', C, None, 'Voice VLAN'),
    'VoiceVLANInterfaceList': ('vlan', 'table', C, 'Entry', 'Voice VLAN per port'),
    'VoiceVLANOUIList': ('vlan', 'table', N, 'Entry', 'Voice VLAN vendor prefixes'),
    # spanning tree and loops
    'STP': ('stp', 'setting', C, None, 'Spanning tree per port'),
    'SpanningTreeGlobalParam': ('stp', 'setting', C, None, 'Spanning tree'),
    'RSTP': ('stp', 'setting', C, None, 'Rapid spanning tree'),
    'MSTPInstanceList': ('stp', 'table', C, 'Entry', 'MSTP instances'),
    'MSTPInterfaceList': ('stp', 'table', C, 'Entry', 'MSTP per port'),
    'MSTPLogicalInstanceList': ('stp', 'table', C, 'Entry', 'MSTP logical instances'),
    'MSTPVLANList': ('stp', 'table', C, 'Entry', 'MSTP VLAN mapping'),
    'LoopbackDetectionGlobalSetting': ('stp', 'setting', N, None, 'Loop protection'),
    'LoopbackDetectionList': ('stp', 'table', N, 'Entry', 'Loop protection per port'),
    # multicast
    'MulticastGlobalSetting': ('mcast', 'setting', N, None, 'Multicast'),
    'IGMPMLDSnoopVLANList': ('mcast', 'table', N, 'Entry', 'IGMP/MLD snooping per VLAN'),
    'IGMPMLDSnoopRouterPortList': ('mcast', 'table', N, 'Entry', 'Multicast router ports'),
    'MulticastMgmtList': ('mcast', 'table', N, 'Entry', 'Multicast groups'),
    'UnregedMulticastList': ('mcast', 'table', N, 'Entry', 'Unregistered multicast'),
    'ReservedMulticastList': ('mcast', 'table', N, 'Entry', 'Reserved multicast'),
    # QoS
    'QoSSettingGlobalParam': ('qos', 'setting', C, None, 'QoS mode'),
    'CoSSetting': ('qos', 'setting', C, None, 'Class of service'),
    'CoSToQueueMappingList': ('qos', 'table', C, 'Entry', 'CoS to queue'),
    'DSCPMapping': ('qos', 'table', C, 'Entry', 'DSCP to queue'),
    'QueueSetting': ('qos', 'setting', C, None, 'Queues'),
    'QoSBandwidthList': ('qos', 'table', C, 'Entry', 'Bandwidth limits'),
    # security
    'DOSGlobalSettings': ('security', 'setting', C, None, 'Denial of service protection'),
    'DOSPreventionTable': ('security', 'table', C, 'Entry', 'DoS prevention rules'),
    'SynRateProtectionTable': ('security', 'table', C, 'Entry', 'SYN rate protection'),
    'InterfaceSecurityTable': ('security', 'table', C, 'Entry', 'Port security'),
    'DHCPSnoopingGlobalSetting': ('security', 'setting', C, None, 'DHCP snooping'),
    'DHCPSnoopingVLANList': ('security', 'table', C, 'VLAN', 'DHCP snooping per VLAN'),
    'DHCPSnoopingInterfaceList': ('security', 'table', C, 'Interface', 'DHCP snooping trusted ports'),
    'DHCPSnoopingBindingList': ('security', 'table', C, 'Entry', 'DHCP snooping bindings'),
    'ARPInspectionGlobalSetting': ('security', 'setting', C, None, 'ARP inspection'),
    'ARPInspectionVLANList': ('security', 'table', C, 'Entry', 'ARP inspection per VLAN'),
    'ARPInspectionTrustInterfaceList': ('security', 'table', C, 'Entry', 'ARP inspection trusted ports'),
    'ARPInspectionList': ('security', 'table', C, 'Entry', 'ARP inspection lists'),
    'IPSourceGuardGlobalSetting': ('security', 'setting', C, None, 'IP source guard'),
    'IPSourceGuardInterfaceList': ('security', 'table', C, 'Interface', 'IP source guard per port'),
    'Standard_802_1xGlobalSetting': ('security', 'setting', C, None, '802.1X authentication'),
    'Standard_802_1xInterfaceList': ('security', 'table', C, 'Entry', '802.1X per port'),
    'Standard_802_1xCredentialsList': ('security', 'table', B, 'Entry', '802.1X credentials'),
    'ACLList': ('security', 'table', B, 'Entry', 'Access lists'),
    'ACEList': ('security', 'table', B, 'Entry', 'Access list rules'),
    'ACLBindingList': ('security', 'table', B, 'Entry', 'Access list bindings'),
    'ClassMapList': ('security', 'table', B, 'Entry', 'Class maps'),
    'PolicyMapList': ('security', 'table', B, 'Entry', 'Policy maps'),
    'PolicyMapBindingList': ('security', 'table', B, 'Entry', 'Policy bindings'),
    # IP services
    'DNSGlobalSetting': ('ip', 'setting', N, None, 'DNS client'),
    'NameServerList': ('ip', 'table', N, 'Entry', 'DNS servers'),
    'StaticHostNameToAddrList': ('ip', 'table', N, 'Entry', 'Static host names'),
    'DNSClearHost': ('ip', 'setting', N, None, 'Clear DNS cache'),
    'ARPGlobalSetting': ('ip', 'setting', N, None, 'ARP aging'),
    'ARPList': ('ip', 'table', N, 'Entry', 'ARP table'),
    'ARPInterfaceSettingTable': ('ip', 'table', N, 'Entry', 'ARP per interface'),
    'IPv6NeighborList': ('ip', 'table', N, 'Entry', 'IPv6 neighbours'),
    'IPv6PrefixList': ('ip', 'table', C, 'Entry', 'IPv6 prefixes'),
    'IPv6RouterAdvertList': ('ip', 'table', C, 'Entry', 'IPv6 router advertisements'),
    'DHCPRelayGlobalSetting': ('ip', 'setting', C, None, 'DHCP relay'),
    'DHCPRelayInterfaceList': ('ip', 'table', C, 'Entry', 'DHCP relay interfaces'),
    'DHCPRelayServerList': ('ip', 'table', C, 'Entry', 'DHCP relay servers'),
    'DHCPv6RelayList': ('ip', 'table', C, 'Entry', 'DHCPv6 relay'),
    'DHCPv6RelayInterfaceList': ('ip', 'table', C, 'Entry', 'DHCPv6 relay interfaces'),
    'DHCPv6RelayDestinationInterfaceList': ('ip', 'table', C, 'Entry', 'DHCPv6 relay destinations'),
    'DHCPSrvGlobalSetting': ('ip', 'setting', C, None, 'DHCP server'),
    'DHCPSrvNetworkPoolList': ('ip', 'table', C, 'Entry', 'DHCP server pools'),
    'DHCPSrvHostPoolList': ('ip', 'table', C, 'Entry', 'DHCP server reservations'),
    'DHCPSrvExcludedNetworkList': ('ip', 'table', C, 'Entry', 'DHCP server excluded addresses'),
    'DHCPSrvOptionList': ('ip', 'table', C, 'Entry', 'DHCP server options'),
    'DHCPSrvBindingList': ('ip', 'table', C, 'Entry', 'DHCP server leases'),
    'PingInetTable': ('ip', 'table', N, 'Entry', 'Ping'),
    'TracerouteInetTable': ('ip', 'table', N, 'Entry', 'Traceroute'),
    # logging and monitoring
    'LogGlobalSetting': ('monitor', 'setting', N, None, 'Log levels'),
    'SyslogGlobalSetting': ('monitor', 'setting', N, None, 'Remote syslog'),
    'SyslogServerList': ('monitor', 'table', N, 'SyslogServer', 'Syslog servers'),
    'MemoryLogTable': ('monitor', 'table', N, 'Entry', 'Memory log'),
    'FlashLogTable': ('monitor', 'table', N, 'Entry', 'Flash log'),
    'LLDPGlobalSetting': ('monitor', 'setting', N, None, 'LLDP'),
    'LLDPInterfaceList': ('monitor', 'table', N, 'InterfaceEntry', 'LLDP per port'),
    'LLDPMEDInterfaceList': ('monitor', 'table', N, 'Entry', 'LLDP-MED per port'),
    'SNMPGlobalSetting': ('monitor', 'setting', N, None, 'SNMP'),
    'CommunityList': ('monitor', 'table', N, 'Entry', 'SNMP communities'),
    'SNMPGroupList': ('monitor', 'table', N, 'Entry', 'SNMP groups'),
    'SNMPUserISList': ('monitor', 'table', N, 'Entry', 'SNMP users'),
    'ViewOIDList': ('monitor', 'table', N, 'Entry', 'SNMP views'),
    'SNMPRemoteEngineIDList': ('monitor', 'table', N, 'Entry', 'SNMP engine IDs'),
    'SNMPTrap': ('monitor', 'setting', N, None, 'SNMP traps'),
    'NotificationReceiverList': ('monitor', 'table', N, 'Entry', 'SNMP trap receivers'),
    'NotificationFilterList': ('monitor', 'table', N, 'Entry', 'SNMP trap filters'),
    'RMONAlarmsTable': ('monitor', 'table', N, 'Entry', 'RMON alarms'),
    'RMONEventTable': ('monitor', 'table', N, 'Entry', 'RMON events'),
    'RMONHistoryControlTable': ('monitor', 'table', N, 'Entry', 'RMON history'),
    # management access: read-only
    'ManagementInterfaceGlobalSetting': ('mgmt', 'setting', B, None, 'Management VLAN'),
    'ManagementIpv4AddressTable': ('mgmt', 'table', B, 'Entry', 'Management IPv4 address'),
    'ManagementIpv6AddressTable': ('mgmt', 'table', B, 'Entry', 'Management IPv6 address'),
    'ManagementIpv6InterfaceSetting': ('mgmt', 'setting', B, None, 'Management IPv6'),
    'IPv4GlobalSetting': ('mgmt', 'setting', B, None, 'IPv4 routing'),
    'IPv4InterfaceList': ('mgmt', 'table', B, 'Entry', 'IPv4 interfaces'),
    'IPv6GlobalSetting': ('mgmt', 'setting', B, None, 'IPv6'),
    'IPv6InterfaceList': ('mgmt', 'table', B, 'Entry', 'IPv6 interfaces'),
    'IPv6AddressList': ('mgmt', 'table', B, 'Entry', 'IPv6 addresses'),
    'IPv6RouteList': ('mgmt', 'table', B, 'Entry', 'IPv6 routes'),
    'InetStaticRouteTable': ('mgmt', 'table', B, 'Entry', 'Static routes'),
    'DHCPv6ClientInterfaceList': ('mgmt', 'table', B, 'Entry', 'DHCPv6 client'),
    'EWSServiceTable': ('mgmt', 'table', B, 'Entry', 'Web interface (HTTP/HTTPS)'),
    'EWSGlobalSetting': ('mgmt', 'setting', B, None, 'Web interface settings'),
    'SSLCryptoCertificateImportList': ('mgmt', 'table', B, 'Entry', 'Certificates'),
    'AdminUserSetting': ('mgmt', 'table', B, 'Entry', 'User accounts'),
    'PasswordComplexity': ('mgmt', 'setting', B, None, 'Password rules'),
    'PasswordComplexityExcludeKeywordList': ('mgmt', 'table', B, 'Entry', 'Forbidden password words'),
    'PasswordGlobalParam': ('mgmt', 'setting', B, None, 'Password ageing'),
    'AAAGlobalSetting': ('mgmt', 'setting', B, None, 'Login authentication'),
    'RadiusDefaultParam': ('mgmt', 'setting', B, None, 'RADIUS defaults'),
    'RadiusServerList': ('mgmt', 'table', B, 'Entry', 'RADIUS servers'),
    'ImageUnitList': ('mgmt', 'table', B, 'Entry', 'Firmware images'),
}

# Field names that identify a table row; they are sent with every change
# to a row so the switch knows which row is meant.
KEY_FIELDS = (
    'interfaceName', 'interfaceType', 'VLANID', 'vlanId', 'unitID', 'IPAddress', 'IPAddr', 'MACAddress',
    'ifIndex', 'sessionId', 'instanceId', 'instanceID', 'index', 'ACLName', 'name', 'userName', 'groupName',
    'communityName', 'viewName', 'timeRangeName', 'poolName', 'OUI', 'LAGID', 'queueID', 'CoS', 'DSCP',
    'hostName', 'serverAddress', 'inetAddress', 'prefix', 'prefixLength', 'engineID', 'receiverAddress',
    'filterName', 'alarmIndex', 'eventIndex', 'historyIndex', 'trapType',
)

# Which fields hold a switch port name
PORT_FIELDS = ('interfaceName', 'ifName', 'portName')

READ_BATCH = 6


def info(name):
    entry = SECTIONS.get(name)
    if not entry:
        return None
    group, kind, risk, row, title = entry
    return {'name': name, 'group': group, 'kind': kind, 'risk': risk, 'row': row, 'title': title}


def sections_of(group):
    return [n for n, e in SECTIONS.items() if e[0] == group]
