#!/bin/sh
#
# Remove a plugin installed with install.sh. Settings stay in config.xml;
# collected data in /var/db/instanton is removed.
#
set -e
[ "$(id -u)" = "0" ] || { echo "run as root" >&2; exit 1; }
SRC="$(cd "$(dirname "$0")" && pwd)/src"

/usr/local/etc/rc.d/instanton stop 2>/dev/null || true
(cd "${SRC}" && find . -type f) | while read -r f; do
	rm -f "/usr/local/${f#./}"
done
rmdir /usr/local/opnsense/scripts/instanton/lib /usr/local/opnsense/scripts/instanton \
	/usr/local/opnsense/mvc/app/controllers/OPNsense/InstantOn/Api \
	/usr/local/opnsense/mvc/app/controllers/OPNsense/InstantOn/forms \
	/usr/local/opnsense/mvc/app/controllers/OPNsense/InstantOn \
	/usr/local/opnsense/mvc/app/models/OPNsense/InstantOn/Menu \
	/usr/local/opnsense/mvc/app/models/OPNsense/InstantOn/ACL \
	/usr/local/opnsense/mvc/app/models/OPNsense/InstantOn \
	/usr/local/opnsense/mvc/app/views/OPNsense/InstantOn \
	/usr/local/opnsense/service/templates/OPNsense/InstantOn \
	/usr/local/opnsense/www/js/instanton 2>/dev/null || true
rm -rf /var/db/instanton /usr/local/etc/instanton /etc/rc.conf.d/instanton /var/run/instanton.pid
rm -f /tmp/opnsense_menu_cache.xml /tmp/opnsense_acl_cache.json /var/lib/php/tmp/opnsense_menu_cache.xml /var/lib/php/tmp/opnsense_acl_cache.json
service configd restart
configctl template reload OPNsense/Syslog
/usr/local/sbin/pluginctl -s syslog restart >/dev/null 2>&1 || true
echo ">>> removed"
