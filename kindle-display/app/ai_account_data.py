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
    if type(value['schema_version']) is not int or value['schema_version'] not in (1, 2):
        raise ValueError('Unsupported schema')
    timestamp(value['collected_at'], False)
    if not isinstance(value['accounts'], list) or not 0 <= len(value['accounts']) <= 40:
        raise ValueError('Invalid account count')
    ids = set()
    for account in value['accounts']:
        keys(account, 'id name plan updated_at reset_credits status windows ' +
             ('expires_at' if value['schema_version'] == 1 else 'subscription'))
        text(account['id'], 80)
        if account['id'] in ids:
            raise ValueError('Duplicate account')
        ids.add(account['id'])
        text(account['name'], 320)
        text(account['plan'], 60)
        timestamp(account['updated_at'])
        if value['schema_version'] == 1:
            timestamp(account['expires_at'])
        else:
            sub = account['subscription']
            keys(sub, 'plan_code cycle_ends_at entitlement_ends_at active will_renew is_delinquent updated_at source status')
            if sub['plan_code'] is not None:
                import re
                if not isinstance(sub['plan_code'], str) or not re.fullmatch(r'[a-z0-9_-]{1,60}', sub['plan_code']):
                    raise ValueError('Invalid plan code')
            for field in ('cycle_ends_at', 'entitlement_ends_at', 'updated_at'):
                timestamp(sub[field])
            for field in ('active', 'will_renew', 'is_delinquent'):
                if sub[field] is not None and type(sub[field]) is not bool:
                    raise ValueError('Invalid subscription flag')
            if sub['source'] not in ('subscriptions', 'account_check', 'id_token', 'none') or sub['status'] not in ('ok', 'cached', 'unknown'):
                raise ValueError('Invalid subscription provenance')
            if sub['status'] == 'ok' and (sub['updated_at'] is None or sub['source'] not in ('subscriptions', 'account_check')):
                raise ValueError('Invalid subscription observation')
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
