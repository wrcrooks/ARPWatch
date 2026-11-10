"""
    Shared code for the ARPWatch plugin: configuration, neighbour table
    parsing, the device database and the notification transports.

    SPDX-License-Identifier: BSD-2-Clause
"""
import configparser
import csv
import ipaddress
import json
import os
import re
import smtplib
import socket
import sqlite3
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

CONFIG_FILE = '/usr/local/etc/arpwatchd.conf'
CONFIG_XML = '/conf/config.xml'
DB_FILE = '/var/db/arpwatch/arpwatch.db'
LEASES_ISC = '/var/dhcpd/var/db/dhcpd.leases'
LEASES_KEA = ('/var/db/kea/kea-leases4.csv', '/var/db/kea/kea-leases6.csv')
LEASES_DNSMASQ = '/var/db/dnsmasq.leases'
MAX_LEASE_FILE = 32 * 1024 * 1024
HTTP_TIMEOUT = 20

EVENT_TITLES = {
    'new_mac': 'New device',
    'new_ip': 'Known device using a new IP address',
    'mac_changed': 'IP address moved to a different MAC address',
}


# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------
def read_config_xml(path=CONFIG_XML):
    """ parse the system configuration, returns None when unavailable """
    try:
        return ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None


class Config:
    """
        Settings as rendered by the configd template. Credentials are deliberately not part of that
        file, since generated files are world readable. They are read from the system configuration
        (root only) instead.
    """
    SECRETS = {
        ('smtp', 'password'): 'smtp_password',
        ('telegram', 'token'): 'telegram_token',
        ('pushbullet', 'token'): 'pushbullet_token',
    }

    def __init__(self, path=CONFIG_FILE, xml_path=CONFIG_XML):
        self._cp = configparser.RawConfigParser(interpolation=None, strict=False)
        self._cp.optionxform = str
        if os.path.isfile(path):
            self._cp.read(path, encoding='utf-8')
        self._secrets = {}
        root = read_config_xml(xml_path)
        node = root.find('OPNsense/arpwatch/notifications') if root is not None else None
        if node is not None:
            for key, tag in self.SECRETS.items():
                self._secrets[key] = (node.findtext(tag) or '').strip()

    def get(self, section, option, default=''):
        if (section, option) in self.SECRETS:
            return self._secrets.get((section, option)) or default
        try:
            return self._cp.get(section, option).strip()
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default

    def getbool(self, section, option, default=False):
        value = self.get(section, option, None)
        return default if value in (None, '') else value == '1'

    def getint(self, section, option, default=0):
        try:
            return int(self.get(section, option, default))
        except (TypeError, ValueError):
            return default

    def getlist(self, section, option):
        return [x.strip() for x in self.get(section, option).split(',') if x.strip()]

    @property
    def interfaces(self):
        """ {device: friendly name}, empty means all interfaces """
        result = {}
        for item in self.getlist('general', 'interfaces'):
            name, _, device = item.partition('|')
            if device:
                result[device] = name
        return result


# --------------------------------------------------------------------------
# neighbour tables
# --------------------------------------------------------------------------
_ARP_RE = re.compile(r'\((?P<ip>[^)]+)\) at (?P<mac>[0-9a-fA-F:]+) on (?P<intf>\S+)(?P<rest>.*)')


def normalize_mac(mac):
    """ return lower case zero padded mac address or None when invalid """
    parts = mac.strip().lower().replace('-', ':').split(':')
    if len(parts) != 6:
        return None
    try:
        if any(not 0 <= int(p, 16) <= 255 for p in parts):
            return None
    except ValueError:
        return None
    return ':'.join(p.zfill(2) for p in parts)


def valid_ip(address):
    try:
        ipaddress.ip_address(address)
        return True
    except ValueError:
        return False


def is_unicast(mac):
    return mac != '00:00:00:00:00:00' and not int(mac[:2], 16) & 1


def is_random_mac(mac):
    """ locally administered bit set, usually a randomised "private" address """
    return bool(int(mac[:2], 16) & 2)


def parse_arp(text):
    """ parse `arp -an`, skipping incomplete and permanent (our own) entries """
    for line in text.splitlines():
        match = _ARP_RE.search(line)
        if not match or 'permanent' in match.group('rest'):
            continue
        mac = normalize_mac(match.group('mac'))
        if mac and is_unicast(mac) and valid_ip(match.group('ip')):
            yield match.group('ip'), mac, match.group('intf')


def parse_ndp(text):
    """ parse `ndp -an`, skipping incomplete and permanent (our own) entries """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[3] == 'permanent':
            continue
        mac = normalize_mac(parts[1])
        address = parts[0].split('%')[0]
        if mac and is_unicast(mac) and valid_ip(address):
            yield address, mac, parts[2]


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False).stdout


def read_neighbours(ipv6=True, run=_run):
    """ return a list of (ip, mac, interface) currently known to the kernel """
    result = list(parse_arp(run(['/usr/sbin/arp', '-an'])))
    if ipv6:
        result.extend(parse_ndp(run(['/usr/sbin/ndp', '-an'])))
    return result


def clean_hostname(name):
    """
        Hostnames are supplied by the devices themselves (dhcp requests, reverse dns), treat them as
        hostile: only keep characters that are harmless in the web interface, in logs and in messages.
    """
    return re.sub(r'[^A-Za-z0-9._-]', '', str(name or '')).strip('.-')[:253]


def clean_text(text):
    """ strip markup and control characters from descriptive text """
    return re.sub(r'[<>"\'`\x00-\x1f\x7f]', '', str(text or ''))[:128].strip()


def lookup_vendor(mac):
    if is_random_mac(mac):
        return 'randomised / locally administered address'
    try:
        from netaddr import EUI
        return clean_text(EUI(mac).oui.registration().org)
    except Exception:  # netaddr missing or prefix not registered
        return ''


def _read_text(path):
    """ read a lease file, empty when missing or implausibly large """
    try:
        if os.path.getsize(path) > MAX_LEASE_FILE:
            return ''
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except OSError:
        return ''


def parse_isc_leases(text):
    """ ISC dhcpd leases file, later entries win """
    result = {}
    for match in re.finditer(r'^lease\s+\S+\s*\{(.*?)^\}', text, re.S | re.M):
        mac = re.search(r'hardware ethernet\s+([0-9a-fA-F:]+)\s*;', match.group(1))
        name = re.search(r'client-hostname\s+"([^"]*)"\s*;', match.group(1))
        if mac and name:
            result[mac.group(1)] = name.group(1)
    return result


def parse_kea_leases(text):
    """ Kea memfile lease database (csv with header), later entries win """
    result = {}
    try:
        for row in csv.DictReader(text.splitlines()):
            if row.get('hwaddr') and row.get('hostname'):
                result[row['hwaddr']] = row['hostname']
    except csv.Error:
        pass
    return result


def parse_dnsmasq_leases(text):
    """ dnsmasq leases: expiry, mac, address, hostname, client id """
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].isdigit() and parts[3] != '*':
            result[parts[1]] = parts[3]
    return result


def static_hostnames(root):
    """ hostnames of static dhcp mappings (ISC, Kea, dnsmasq) found in the system configuration """
    result = {}
    if root is None:
        return result
    sources = (
        ('dhcpd/*/staticmap', 'mac', 'hostname'),
        ('dhcpdv6/*/staticmap', 'mac', 'hostname'),
        ('OPNsense/Kea/dhcp4/reservations/reservation', 'hw_address', 'hostname'),
        ('dnsmasq/hosts', 'hwaddr', 'host'),
    )
    for path, mac_tag, name_tag in sources:
        for node in root.iterfind(path):
            for mac in re.split(r'[,\s]+', node.findtext(mac_tag) or ''):
                if mac and node.findtext(name_tag):
                    result[mac] = node.findtext(name_tag)
    return result


class HostnameDirectory:
    """
        Hostnames by mac address as known to the dhcp services on this firewall. Files are only
        parsed again after they changed.
    """

    def __init__(self, xml_path=CONFIG_XML, isc=LEASES_ISC, kea=LEASES_KEA, dnsmasq=LEASES_DNSMASQ):
        # lowest priority first: dynamic leases, then static mappings
        self._sources = [(isc, lambda p: parse_isc_leases(_read_text(p)))]
        self._sources += [(path, lambda p: parse_kea_leases(_read_text(p))) for path in kea]
        self._sources.append((dnsmasq, lambda p: parse_dnsmasq_leases(_read_text(p))))
        self._sources.append((xml_path, lambda p: static_hostnames(read_config_xml(p))))
        self._cache = {}

    def _load(self, path, parser):
        try:
            stat = os.stat(path)
        except OSError:
            self._cache.pop(path, None)
            return {}
        stamp = (stat.st_mtime_ns, stat.st_size)
        if self._cache.get(path, (None, None))[0] != stamp:
            names = {}
            try:
                for mac, name in parser(path).items():
                    mac, name = normalize_mac(mac), clean_hostname(name)
                    if mac and name:
                        names[mac] = name
            except Exception:  # never let an odd lease file take the daemon down
                names = {}
            self._cache[path] = (stamp, names)
        return self._cache[path][1]

    def by_mac(self):
        result = {}
        for path, parser in self._sources:
            result.update(self._load(path, parser))
        return result


def resolve_hostnames(addresses, timeout=5.0):
    """ reverse resolve addresses in parallel, never blocking longer than timeout """
    results = {}

    def worker(address):
        try:
            name = clean_hostname(socket.gethostbyaddr(address)[0])
            # resolvers echo the address back when there is no name
            if name and not valid_ip(name):
                results[address] = name
        except (OSError, UnicodeError):
            pass

    threads = [threading.Thread(target=worker, args=(a,), daemon=True) for a in list(addresses)[:64]]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    return dict(results)


# --------------------------------------------------------------------------
# database
# --------------------------------------------------------------------------
class Database:
    SCHEMA = """
        create table if not exists hosts (
            mac text primary key,
            first_seen integer not null,
            last_seen integer not null,
            interface text,
            vendor text,
            hostname text
        );
        create table if not exists addresses (
            mac text not null,
            ip text not null,
            first_seen integer not null,
            last_seen integer not null,
            primary key (mac, ip)
        );
        create index if not exists addresses_ip on addresses (ip, last_seen);
    """

    def __init__(self, path=DB_FILE):
        if os.path.dirname(path):
            os.makedirs(os.path.dirname(path), mode=0o750, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(self.SCHEMA)

    def is_empty(self):
        return self.conn.execute('select 1 from hosts limit 1').fetchone() is None

    def observe(self, mac, ip, interface, now):
        """
            record a sighting, returns (event type or None, previous mac of this ip or None).
            caller is responsible for commit()
        """
        cur = self.conn.cursor()
        known_host = cur.execute('select 1 from hosts where mac = ?', (mac,)).fetchone() is not None
        known_addr = cur.execute('select 1 from addresses where mac = ? and ip = ?', (mac, ip)).fetchone() is not None
        owner = cur.execute('select mac from addresses where ip = ? order by last_seen desc limit 1', (ip,)).fetchone()
        previous_mac = owner['mac'] if owner is not None and owner['mac'] != mac else None

        if known_host:
            cur.execute('update hosts set last_seen = ?, interface = ? where mac = ?', (now, interface, mac))
        else:
            cur.execute(
                'insert into hosts (mac, first_seen, last_seen, interface) values (?, ?, ?, ?)',
                (mac, now, now, interface)
            )
        if known_addr:
            cur.execute('update addresses set last_seen = ? where mac = ? and ip = ?', (now, mac, ip))
        else:
            cur.execute('insert into addresses (mac, ip, first_seen, last_seen) values (?, ?, ?, ?)', (mac, ip, now, now))

        if not known_host:
            return 'new_mac', previous_mac
        if previous_mac is not None:
            return 'mac_changed', previous_mac
        if not known_addr:
            return 'new_ip', None
        return None, None

    def set_details(self, mac, vendor=None, hostname=None):
        self.conn.execute(
            'update hosts set vendor = coalesce(?, vendor), hostname = coalesce(?, hostname) where mac = ?',
            (vendor or None, hostname or None, mac)
        )

    def hostnames(self):
        return {r['mac']: r['hostname'] or '' for r in self.conn.execute('select mac, hostname from hosts')}

    def commit(self):
        self.conn.commit()

    def list_hosts(self):
        rows = []
        addresses = {}
        for row in self.conn.execute('select mac, ip from addresses order by last_seen desc'):
            addresses.setdefault(row['mac'], []).append(row['ip'])
        for row in self.conn.execute('select * from hosts order by first_seen desc'):
            rows.append({
                'id': row['mac'].replace(':', ''),
                'mac': row['mac'],
                # sanitise on the way out as well, rows may predate input sanitising
                'vendor': clean_text(row['vendor']),
                'hostname': clean_hostname(row['hostname']),
                'interface': clean_text(row['interface']),
                'addresses': ', '.join(addresses.get(row['mac'], [])),
                'first_seen': format_time(row['first_seen']),
                'last_seen': format_time(row['last_seen']),
            })
        return rows

    def delete(self, mac):
        self.conn.execute('delete from addresses where mac = ?', (mac,))
        deleted = self.conn.execute('delete from hosts where mac = ?', (mac,)).rowcount
        self.conn.commit()
        return deleted > 0

    def flush(self):
        self.conn.execute('delete from addresses')
        self.conn.execute('delete from hosts')
        self.conn.commit()


def format_time(timestamp):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))


# --------------------------------------------------------------------------
# notifications
# --------------------------------------------------------------------------
def format_event(event):
    mac = event['mac']
    if event.get('vendor'):
        mac += ' (%s)' % event['vendor']
    lines = [
        EVENT_TITLES.get(event['type'], event['type']),
        '  MAC address:  %s' % mac,
        '  IP address:   %s' % event['ip'],
    ]
    if event.get('previous_mac'):
        lines.append('  Previous MAC: %s' % event['previous_mac'])
    if event.get('hostname'):
        lines.append('  Hostname:     %s' % event['hostname'])
    lines.append('  Interface:    %s' % event['interface'])
    lines.append('  Time:         %s' % format_time(event['time']))
    return '\n'.join(lines)


def format_notification(events):
    """ return (subject, body) for one or more events """
    firewall = socket.gethostname()
    if len(events) == 1:
        event = events[0]
        where = '%s, %s' % (event['ip'], event['hostname']) if event.get('hostname') else event['ip']
        subject = '[%s] ARPWatch: %s %s (%s)' % (
            firewall, EVENT_TITLES.get(event['type'], event['type']).lower(), event['mac'], where
        )
    else:
        subject = '[%s] ARPWatch: %d events' % (firewall, len(events))
    return subject, '\n\n'.join(format_event(e) for e in events)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """ access tokens travel in the url or headers, never replay them to another location """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _http_post(url, payload, headers=None):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'opnsense-arpwatch', **(headers or {})},
        method='POST'
    )
    try:
        with _OPENER.open(request, timeout=HTTP_TIMEOUT) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        # surface the API's own explanation, never the request url (it may contain a token)
        detail = ''
        try:
            data = json.loads(exc.read().decode('utf-8', 'replace'))
            detail = data.get('description') or (data.get('error') or {}).get('message') or ''
        except Exception:
            pass
        raise RuntimeError('HTTP %d %s' % (exc.code, detail or exc.reason)) from None
    except urllib.error.URLError as exc:
        raise RuntimeError('connection failed: %s' % exc.reason) from None


def send_smtp(cfg, subject, body):
    host = cfg.get('smtp', 'host')
    security = cfg.get('smtp', 'security', 'starttls')
    port = cfg.getint('smtp', 'port', 465 if security == 'ssl' else 587)
    sender = cfg.get('smtp', 'from')
    recipients = cfg.getlist('smtp', 'to')
    if not host or not sender or not recipients:
        raise RuntimeError('SMTP host, sender and recipient are required')

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = ', '.join(recipients)
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid()
    message.set_content(body + '\n')

    context = ssl.create_default_context()
    if security == 'ssl':
        client = smtplib.SMTP_SSL(host, port, timeout=HTTP_TIMEOUT, context=context)
    else:
        client = smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT)
    with client:
        if security == 'starttls':
            client.starttls(context=context)
        if cfg.get('smtp', 'username'):
            client.login(cfg.get('smtp', 'username'), cfg.get('smtp', 'password'))
        client.send_message(message, from_addr=sender, to_addrs=recipients)


def send_telegram(cfg, subject, body):
    token = cfg.get('telegram', 'token')
    chat_id = cfg.get('telegram', 'chat_id')
    if not token or not chat_id:
        raise RuntimeError('Telegram bot token and chat id are required')
    text = '%s\n\n%s' % (subject, body)
    _http_post(
        'https://api.telegram.org/bot%s/sendMessage' % token,
        {'chat_id': chat_id, 'text': text[:4000], 'disable_web_page_preview': True}
    )


def send_pushbullet(cfg, subject, body):
    token = cfg.get('pushbullet', 'token')
    if not token:
        raise RuntimeError('Pushbullet access token is required')
    payload = {'type': 'note', 'title': subject, 'body': body}
    if cfg.get('pushbullet', 'channel'):
        payload['channel_tag'] = cfg.get('pushbullet', 'channel')
    _http_post('https://api.pushbullet.com/v2/pushes', payload, {'Access-Token': token})


NOTIFIERS = {
    'smtp': send_smtp,
    'telegram': send_telegram,
    'pushbullet': send_pushbullet,
}


def enabled_notifiers(cfg):
    return [name for name in NOTIFIERS if cfg.getbool(name, 'enabled')]


def send(cfg, name, subject, body):
    """ deliver via a single transport, returns None on success or the error text """
    try:
        NOTIFIERS[name](cfg, subject, body)
        return None
    except Exception as exc:
        return str(exc) or exc.__class__.__name__
