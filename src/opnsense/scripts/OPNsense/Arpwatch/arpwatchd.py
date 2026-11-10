#!/usr/local/bin/python3

"""
    ARPWatch daemon: polls the kernel ARP / NDP tables, keeps a database of
    every MAC address seen and notifies when something new shows up.

    SPDX-License-Identifier: BSD-2-Clause
"""
import signal
import syslog
import threading
import time

from arpwatch_common import (
    Config, Database, HostnameDirectory, enabled_notifiers, format_notification, lookup_vendor,
    read_neighbours, resolve_hostnames, send
)

MAX_ATTEMPTS = 5
CHANGE_COOLDOWN = 3600
DNS_RETRY = 600
DNS_BATCH = 64


class Watcher:
    def __init__(self, cfg, db, neighbours=read_neighbours, clock=time.time, directory=None):
        self.cfg = cfg
        self.db = db
        self.neighbours = neighbours
        self.clock = clock
        self.directory = directory or HostnameDirectory()
        self.interfaces = cfg.interfaces
        self.ignore = [x.lower() for x in cfg.getlist('general', 'ignore_macs')]
        self.wanted = {
            'new_mac': cfg.getbool('general', 'notify_new_mac', True),
            'new_ip': cfg.getbool('general', 'notify_new_ip', False),
            'mac_changed': cfg.getbool('general', 'notify_mac_changed', True),
        }
        # when starting with an empty database the first scan only learns what is out there
        self.learning = cfg.getbool('general', 'silent_seed', True) and db.is_empty()
        self.retry_queue = []
        self.last_change = {}
        self.dns_tried = {}
        self.held = []

    def log(self, message, priority=syslog.LOG_NOTICE):
        syslog.syslog(priority, message)

    def describe_interface(self, device):
        name = self.interfaces.get(device)
        return '%s (%s)' % (device, name) if name else device

    def refresh_hostnames(self, present, now):
        """
            Bring the stored hostnames of the devices currently visible up to date. DHCP knowledge
            (static mappings, leases) wins, reverse dns fills the gaps. Returns {mac: hostname}.
        """
        known = self.db.hostnames()
        leases = self.directory.by_mac()
        lookups = {}
        for mac, ip in present.items():
            if leases.get(mac):
                if known.get(mac) != leases[mac]:
                    known[mac] = leases[mac]
                    self.db.set_details(mac, hostname=leases[mac])
            elif not known.get(mac) and len(lookups) < DNS_BATCH:
                # a name is often registered moments after a device appears, so the second
                # attempt follows on the next scan, later ones are spaced out
                tries, last = self.dns_tried.get(mac, (0, 0))
                if tries == 0 or (tries == 1 and now > last) or now - last >= DNS_RETRY:
                    self.dns_tried[mac] = (tries + 1, now)
                    lookups[mac] = ip
        if lookups:
            resolved = resolve_hostnames(set(lookups.values()))
            for mac, ip in lookups.items():
                if resolved.get(ip):
                    known[mac] = resolved[ip]
                    self.db.set_details(mac, hostname=resolved[ip])
        for mac in [m for m in self.dns_tried if m not in present or known.get(m)]:
            del self.dns_tried[mac]
        # leases also name devices that are not visible right now (held events)
        return {**leases, **{mac: name for mac, name in known.items() if name}}

    def scan(self):
        now = int(self.clock())
        events = []
        present = {}
        for ip, mac, device in self.neighbours(self.cfg.getbool('general', 'ipv6', True)):
            if self.interfaces and device not in self.interfaces:
                continue
            # prefer an IPv4 address for reverse lookups
            if mac not in present or (':' in present[mac] and ':' not in ip):
                present[mac] = ip
            kind, previous_mac = self.db.observe(mac, ip, device, now)
            if kind is None:
                continue
            if kind == 'mac_changed':
                # two stations fighting over an address flip on every scan, do not flood
                if ip in self.last_change and now - self.last_change[ip] < CHANGE_COOLDOWN:
                    continue
                self.last_change[ip] = now
            events.append({
                'type': kind, 'mac': mac, 'ip': ip, 'previous_mac': previous_mac,
                'interface': self.describe_interface(device), 'time': now
            })

        hostnames = self.refresh_hostnames(present, now)
        for event in events:
            event['vendor'] = lookup_vendor(event['mac'])
            event['hostname'] = hostnames.get(event['mac'], '')
            if event['type'] == 'new_mac':
                self.db.set_details(event['mac'], vendor=event['vendor'])
            self.log('%s%s: %s %s%s on %s%s' % (
                'learned ' if self.learning else '', event['type'], event['mac'], event['ip'],
                ' (%s)' % event['hostname'] if event['hostname'] else '', event['interface'],
                ' (was %s)' % event['previous_mac'] if event['previous_mac'] else ''
            ))
        self.db.commit()

        if self.learning:
            self.learning = False
            self.log('initial scan complete, %d address(es) learned without notification' % len(events))
            return []

        # events held back last time waited one scan for a hostname, send them with or without
        ready, self.held = self.held, []
        for event in ready:
            event['hostname'] = hostnames.get(event['mac'], '')
        for event in events:
            if not self.wanted.get(event['type']) or self.is_ignored(event['mac']):
                continue
            (ready if event['hostname'] else self.held).append(event)
        return ready

    def is_ignored(self, mac):
        return any(mac.startswith(prefix) for prefix in self.ignore)

    def notify(self, events):
        if not events:
            return
        subject, body = format_notification(events)
        for name in enabled_notifiers(self.cfg):
            self.deliver({'name': name, 'subject': subject, 'body': body, 'attempts': 0, 'due': 0})

    def deliver(self, item):
        error = send(self.cfg, item['name'], item['subject'], item['body'])
        if error is None:
            self.log('%s notification sent: %s' % (item['name'], item['subject']), syslog.LOG_INFO)
            return
        item['attempts'] += 1
        if item['attempts'] >= MAX_ATTEMPTS:
            self.log('%s notification dropped after %d attempts: %s' % (
                item['name'], item['attempts'], error
            ), syslog.LOG_ERR)
            return
        item['due'] = self.clock() + 60 * 2 ** (item['attempts'] - 1)
        self.retry_queue.append(item)
        self.log('%s notification failed (attempt %d), will retry: %s' % (
            item['name'], item['attempts'], error
        ), syslog.LOG_WARNING)

    def retry(self):
        due = [i for i in self.retry_queue if i['due'] <= self.clock()]
        self.retry_queue = [i for i in self.retry_queue if i['due'] > self.clock()]
        for item in due:
            self.deliver(item)

    def run_once(self):
        self.retry()
        self.notify(self.scan())


def main():
    syslog.openlog('arpwatch', syslog.LOG_PID, syslog.LOG_DAEMON)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    cfg = Config()
    watcher = Watcher(cfg, Database())
    interval = max(5, cfg.getint('general', 'interval', 30))
    watcher.log('started, watching %s every %d seconds, notifying via %s' % (
        ', '.join(watcher.interfaces) or 'all interfaces', interval,
        ', '.join(enabled_notifiers(cfg)) or 'nothing (no notification method enabled)'
    ))
    while not stop.is_set():
        try:
            watcher.run_once()
        except Exception as exc:
            watcher.log('scan failed: %s: %s' % (exc.__class__.__name__, exc), syslog.LOG_ERR)
        stop.wait(interval)
    watcher.log('stopped')


if __name__ == '__main__':
    main()
