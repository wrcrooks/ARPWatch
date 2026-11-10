#!/usr/local/bin/python3

"""
    Send a test message through every enabled notification method and
    report the outcome per method as json.

    SPDX-License-Identifier: BSD-2-Clause
"""
import json
import socket

from arpwatch_common import Config, enabled_notifiers, send

if __name__ == '__main__':
    cfg = Config()
    subject = '[%s] ARPWatch: test notification' % socket.gethostname()
    body = 'This is a test notification from the ARPWatch plugin. If you can read this, delivery works.'
    results = {}
    for name in enabled_notifiers(cfg):
        error = send(cfg, name, subject, body)
        results[name] = {'success': error is None, 'message': error or 'sent'}
    print(json.dumps({
        'status': 'ok' if results and all(r['success'] for r in results.values()) else 'failed',
        'results': results
    }))
