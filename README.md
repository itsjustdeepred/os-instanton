# os-instanton

OPNsense plugin that monitors HPE Networking (Aruba) Instant On switches and
access points from the firewall web interface. It only reads: nothing is
ever changed on the devices.

## What it shows

| Page | Content |
|---|---|
| **Overview** | Status cards, health checks, recent events, switch front panel, access point list |
| **Switch** | Device and health data (temperature, fans, PSU, PoE budget, clock, unsaved config, web sessions), front panel, every port with link, role, LLDP neighbour, VLANs, PoE, throughput, totals, learned MACs, errors and link flaps, VLAN table, switch log with level filter |
| **Access Points** | Model, IP, uplink port/speed/PoE, wireless clients, firmware, serial, coordinator, cloud and time-sync status, last restart reason (crashes highlighted); cloud inventory with radios when the cloud source is on |
| **Clients** | Every learned device with name, IP, MAC/vendor, private-MAC detection, access point or port, VLAN, first/last seen, signal (cloud); filters and CSV export |
| **Events** | Port up/down, access point offline/restart/firmware/coordinator changes, new devices, PoE faults, polling failures; also sent to syslog |
| **Settings** | Sources, credentials, polling, thresholds, with field help, service control and a connection test |
| **Dashboard widget** | Switch, access points, clients, PoE and open problems |

### Health checks

Wrong switch clock or missing SNTP server, unsaved switch configuration,
unexpected restart, temperature/fan/PSU alarms, PoE budget usage, ports
that keep going down (switch-wide outages are ignored), packet errors,
half duplex, access points linked below 1 Gb/s, PoE faults, unreachable
access points, failing NTP on access points, firmware crashes, meshed
access points, mixed firmware, devices without IP or name.

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
  authentication are not supported. This source has not been tested against
  a live account yet.

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

Then open **Services > Instant On > Settings**, enter the switch address
and an account of its web interface, press **Test connection**, tick
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
| `/var/log/instanton/` | Syslog output (Services > Instant On > Log File) |

configd actions: `instanton start|stop|restart|status|refresh|test`,
`instanton view <summary|switch|ports|aps|clients|events|log|insights|all>`.

API (all read-only except the service endpoints):

```
GET  /api/instanton/status/{summary,switch,ports,aps,clients,events,log,insights}
GET  /api/instanton/settings/get        POST /api/instanton/settings/set
POST /api/instanton/service/{start,stop,restart,reconfigure,refresh,test}
GET  /api/instanton/service/status
```

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
