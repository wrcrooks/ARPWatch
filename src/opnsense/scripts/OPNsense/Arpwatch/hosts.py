#!/usr/local/bin/python3

"""
    Query / maintain the ARPWatch device database.
    usage: hosts.py list | delete <12 hex digits> | flush

    SPDX-License-Identifier: BSD-2-Clause
"""
import json
import re
import sys

from arpwatch_common import Database

if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'list'
    db = Database()
    if action == 'list':
        print(json.dumps({'rows': db.list_hosts()}))
    elif action == 'delete' and len(sys.argv) > 2 and re.fullmatch(r'[0-9a-f]{12}', sys.argv[2]):
        mac = ':'.join(re.findall('..', sys.argv[2]))
        print('OK' if db.delete(mac) else 'NOTFOUND')
    elif action == 'flush':
        db.flush()
        print('OK')
    else:
        print('ERROR')
        sys.exit(1)
