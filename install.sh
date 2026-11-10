#!/bin/sh
#
# Install (or with "remove": uninstall) the plugin straight from this checkout,
# without building a package. Run as root on the OPNsense firewall.

set -e

SRC="$(cd "$(dirname "$0")" && pwd)/src"
DST=/usr/local

if [ "$(id -u)" != "0" ]; then
    echo "must be run as root" >&2
    exit 1
fi
if [ ! -d /usr/local/opnsense/mvc ]; then
    echo "this does not look like an OPNsense system" >&2
    exit 1
fi

FILES=$(cd "${SRC}" && find . -type f | sed 's|^\./||')

if [ "$1" = "remove" ]; then
    /usr/local/etc/rc.d/arpwatchd onestop 2>/dev/null || true
    for FILE in ${FILES}; do
        rm -f "${DST}/${FILE}"
    done
    rm -f /etc/rc.conf.d/arpwatchd /usr/local/etc/arpwatchd.conf
    echo "removed (device database kept in /var/db/arpwatch, settings kept in config.xml)"
else
    for FILE in ${FILES}; do
        mkdir -p "$(dirname "${DST}/${FILE}")"
        cp "${SRC}/${FILE}" "${DST}/${FILE}"
    done
    chmod 755 ${DST}/etc/rc.d/arpwatchd ${DST}/opnsense/scripts/OPNsense/Arpwatch/*.py
    chmod 644 ${DST}/opnsense/scripts/OPNsense/Arpwatch/arpwatch_common.py
    echo "installed"
fi

# make the system pick up the changes: configd actions, syslog target, menu / acl / view caches
service configd restart
rm -f /usr/local/opnsense/mvc/app/cache/*.php /tmp/opnsense_menu_cache.xml /tmp/opnsense_acl_cache.json
/usr/local/etc/rc.configure_plugins 2>/dev/null || true
if [ "$1" != "remove" ]; then
    configctl template reload OPNsense/Arpwatch
    configctl arpwatch restart 2>/dev/null || true
    echo "done, open Services > ARPWatch in the web interface"
fi
