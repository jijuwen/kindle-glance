"""Strict, credential-free interchange format shared by the collector and receiver."""
from __future__ import annotations

import math

MAX_BYTES = 262144


def validate_snapshot(value):
    def keys(obj, expected):
        if not isinstance(obj, dict) or set(obj) != set(expected.split()):
            raise ValueError('Unexpected snapshot fields')

    def text(value, limit):
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid text')

    def timestamp(value, optional=True):
        if optional and value is None:
            return
        if type(value) is not int or not 946684800 <= value <= 7258118400:
            raise ValueError('Expected Unix seconds')

    keys(value, 'schema_version collected_at accounts')
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Unsupported schema')
    timestamp(value['collected_at'], False)
    if not isinstance(value['accounts'], list) or not 0 <= len(value['accounts']) <= 40:
        raise ValueError('Invalid account count')
    ids = set()
    for account in value['accounts']:
        keys(account, 'id name plan updated_at expires_at reset_credits status windows')
        text(account['id'], 80)
        if account['id'] in ids:
            raise ValueError('Duplicate account')
        ids.add(account['id'])
        text(account['name'], 320)
        text(account['plan'], 60)
        timestamp(account['updated_at'])
        timestamp(account['expires_at'])
        if account['status'] not in ('ok', 'refresh_error', 'reauth_required', 'unknown'):
            raise ValueError('Invalid account status')
        credit = account['reset_credits']
        if credit is not None and (type(credit) is not int or not 0 <= credit <= 100000):
            raise ValueError('Invalid reset credits')
        if not isinstance(account['windows'], list) or len(account['windows']) > 12:
            raise ValueError('Invalid window count')
        for window in account['windows']:
            keys(window, 'label remaining_percent reset_at')
            text(window['label'], 100)
            pct = window['remaining_percent']
            if pct is not None and (type(pct) not in (int, float) or not math.isfinite(pct) or not 0 <= pct <= 100):
                raise ValueError('Invalid remaining percentage')
            timestamp(window['reset_at'])
    return value
