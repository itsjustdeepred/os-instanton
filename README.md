# os-instanton

OPNsense plugin that monitors HPE Networking (Aruba) Instant On switches and
access points from the firewall web interface and, when allowed, manages the
switch configuration. By default it only reads.

## What it shows

| Page | Content |
|---|---|
| **Overview** | Status cards, health checks, recent events, a front panel per switch, access point list |
| **Switch** | One tab per switch: device and health data (temperature, fans, PSU, PoE budget, clock, unsaved config, web sessions), front panel, every port with link, role, LLDP neighbour, VLANs, PoE, throughput, totals, learned MACs, errors and link flaps, VLAN table, switch log with level filter |
| **Access Points** | Model, IP, uplink switch/port/speed/PoE, wireless clients, firmware, serial, coordinator, cloud status, clock check, last restart reason (crashes highlighted); with a cloud account also the cloud inventory (health, mesh uplink and its signal, radios) and the Wi-Fi networks (SSID, security, VLAN, bands, clients) |
| **Clients** | Every learned device with its kind (camera, phone, printer, smart home, ...), name, IP, MAC/vendor, private-MAC detection, access point or switch and port, VLAN, first/last seen, SSID and signal (cloud); filters and CSV export |
| **Network Map** | Tree from the firewall to switches, access points (mesh links included) and clients, with port, speed, PoE and signal on every link; clients grouped by kind |
| **Events** | Port up/down, access point offline/restart/firmware/coordinator changes, new devices, PoE faults, polling failures; also sent to syslog |
| **Configuration** | For each switch, every configuration section, grouped like the switch menus, with common tasks (name, time and time server, remote syslog, save, locator LED, restart) and a generic editor |
| **Settings** | List of switches, list of cloud accounts with site selection, access points, polling, thresholds, change permission, with field help, service control and a connection test |
| **Dashboard widget** | Switch, access points, clients, PoE and open problems |

### Health checks

Wrong switch clock or missing SNTP server, unsaved switch configuration,
unexpected restart, temperature/fan/PSU alarms, PoE budget usage, ports
that keep going down (switch-wide outages are ignored), packet errors,
half duplex, access points linked below 1 Gb/s, PoE faults, unreachable
access points, wrong clock on access points, SNTP server not answering the
switch, firmware crashes, meshed access points, mixed firmware, devices
without IP or name.

## Changing the switch

Off until **Allow changes** is ticked in Settings (the switch account then
needs administrator rights). Changes are sent the way the switch web
interface sends them (`<Section action="set|add|delete">` documents POSTed
to `/device/wcd`), then saved to the startup configuration unless
**Save after each change** is off.

* **Switch page**: per port description, enable/disable, PoE on/off, PoE
  power cycle, cable test.
* **Configuration page**: system name/location/contact, SNTP server, time
  zone and daylight saving, remote syslog, save, locator LED, restart; and a
  generic editor for the 148 sections the switch interface can change.

Protection against locking the firewall out:

| Level | Sections | Behaviour |
|---|---|---|
| normal | logging, LLDP, SNMP, multicast, PoE, time, ... | applied directly |
| caution | ports, VLANs, spanning tree, LAG, QoS, DHCP snooping, ARP inspection, 802.1X, storm control, relays, ... | explicit confirmation required |
| blocked | management address and VLAN, IP interfaces and routes, accounts and passwords, login authentication, RADIUS, web service, certificates, firmware images, access lists and policies | read-only |

In every section, rows of the port that leads to the firewall are refused,
and the management VLAN cannot be deleted. Every change is validated before
the switch is contacted and recorded in Events and syslog (area `change`).

Access points take their configuration from the Instant On cloud and have
no local configuration interface; they can be power-cycled through their
PoE port.

## Several switches and cloud accounts

Any number of switches and Instant On cloud accounts can be added in
Settings. Each switch has its own credentials, uplink ports and save option;
each cloud account reads all of its sites or the ones ticked in the site
list. Links between monitored switches are found from LLDP and from the
switch MAC addresses in the forwarding tables. A device is placed on the
edge port where it is learned, not on the links between switches. Links
towards the firewall and between monitored switches are protected from
changes like the uplink of a single switch.

## Device kind

Each client gets a kind (`type`) guessed from, in order: its name
(firewall static mapping, DHCP host name, port description, cloud name),
the cloud fingerprint, LLDP capabilities, and the manufacturer of the MAC
address. The source of the guess is shown in the tooltip of the Type column.

## Data sources

* **Switch (local management)** – Instant On 1930/1960 web API
  (`/device/wcd?{Section}`), RSA-encrypted login like the web UI. The
  monitor keeps one session open between polls: every login and logout
  writes two lines into the switch's small in-memory log, and polling with a
  new session each minute would push the real events out of it.
* **Access points** – unauthenticated diagnostic page
  `http://<ap>:8080/swarm.cgi?opcode=smb_debug_info`, discovered through
  the switch LLDP neighbours or listed by address.
* **Firewall** – ARP table, ISC/Kea/Dnsmasq leases and static mappings
  give IP addresses and names to the MAC addresses learned by the switch.
  Wired ports with a single device and a description name that device.
* **Cloud (optional, experimental)** – the undocumented Instant On portal
  API (OAuth2 + PKCE, `x-ion-api-version: 7`) for SSIDs, signal, band and
  health of wireless clients, radios and alerts. Accounts with two-factor
  authentication are not supported. Tested read-only against a live account
  with one site. The API also returns Wi-Fi passphrases; the plugin never
  stores them.

Wireless client details (SSID, signal, band) are not available locally on
Instant On access points; without the cloud source a client is "wireless"
when the switch learned it on an access point port.

## Installation

The plugin follows the `opnsense/plugins` layout (`Makefile`, `pkg-descr`,
`src/`) and can be built as a package from that tree. For a quick install
on a running firewall, copy this repository to it and run as root:

```sh
sh install.sh
```

Then open **Services > Instant On > Settings**, add the switches (address
and an account of their web interface) and optionally the cloud accounts, press **Test connection**, tick
**Enable monitor** and press **Apply**. `uninstall.sh` removes the files
and the collected data (settings stay in `config.xml`).

## Files and services

| Path | Purpose |
|---|---|
| `/usr/local/etc/rc.d/instanton` | Monitor service (`daemon(8)` + `collect.py --loop`) |
| `/usr/local/etc/instanton/instanton.conf` | Generated settings, mode 0600 |
| `/var/db/instanton/state.json` | Latest snapshot |
| `/var/db/instanton/clients.json` | Device history (first/last seen) |
| `/var/db/instanton/events.json` | Event history |
| `/var/db/instanton/config-<switch id>.json` | Switch configuration sections read for the Configuration page |
| `/var/log/instanton/` | Syslog output (Services > Instant On > Log File) |

configd actions: `instanton start|stop|restart|status|refresh|test`,
`instanton view <summary|switch|ports|aps|clients|events|log|insights|topology|all>[:<switch id>]`,
`instanton readconfig [<switch id>:]<group|Section|all|cached>`,
`instanton configure <base64url JSON request>`, `instanton cloudsites <account id>`.

API:

```
GET  /api/instanton/status/{summary,aps,clients,events,insights,topology}
GET  /api/instanton/status/{switch,ports,log}/<switch id>
GET  /api/instanton/settings/get        POST /api/instanton/settings/set
     /api/instanton/settings/{search,get,add,set,del,toggle}{Switch,Account}
POST /api/instanton/service/{start,stop,restart,reconfigure,refresh,test}
POST /api/instanton/service/cloudsites/<account id>
GET  /api/instanton/service/status
GET  /api/instanton/config/read/<switch id>/cached   POST /api/instanton/config/read/<switch id>/{group|Section|all}
POST /api/instanton/config/apply         request={"switch": <id>, "action": ..., "params": {...}}
```

Actions: `port`, `poe`, `poe_cycle`, `system`, `time`, `syslog`, `locate`,
`cable_test`, `reboot`, `save`, `section` (generic: `section`, `op`
set/add/delete/deleteAll, `values` or `entries`, `confirm`). The ACL
*Services: Instant On: change switch* grants `config/apply`; the base ACL
only reads.

`refresh` asks the running monitor to poll at once (SIGUSR1), or runs one
poll when the monitor is stopped. It also appears in the cron job action
list for scheduled polls without the background service.

## Development

The collector runs on any machine with Python 3.11+ and no extra modules:

```sh
INSTANTON_CONFIG=./instanton.conf INSTANTON_STATE_DIR=./state INSTANTON_DEBUG=1 \
    python3 src/opnsense/scripts/instanton/collect.py
python3 -m unittest discover -s tests
```

The tests use anonymized data captured from a 1960 switch and an AP25 and
do not touch the network.

## License

BSD 2-Clause, see `LICENSE`.
