"""Metadata persistence checks using temporary storage, without OAuth or CLI calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service


class SubscriptionMetadataTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        patches = patch.multiple(service, STATE=root/'state', PUBLIC=root/'public', MODEL={})
        patches.start()
        self.addCleanup(patches.stop)
        service.initialize()
        service.MODEL['enabled'] = True
        for number in (1, 2):
            slot = service.slot_at(number)
            slot.update(bound=True, email=f'test{number}@example.com', plan='PRO', state='ok',
                        snapshot={'id': f'codex-slot-{number}', 'name': f'test{number}@example.com',
                                  'plan': 'PRO', 'updated_at': service.now(), 'expires_at': None,
                                  'reset_credits': 2, 'status': 'ok', 'windows': []})

    def published(self):
        return json.loads((service.PUBLIC/'ai-accounts.json').read_text())['accounts']

    def test_date_survives_restart_and_snapshot_refresh_without_affecting_other_slot(self):
        expiry = 1791460740  # 2026-10-08 19:59 Asia/Shanghai
        service.action(1, 'metadata', {'plan_label': 'PRO', 'expires_at': expiry})
        service.initialize()
        # A fresh quota snapshot has no official subscription expiry.
        service.slot_at(1)['snapshot']['expires_at'] = None
        service.publish()
        self.assertEqual(self.published()[0]['expires_at'], expiry)
        self.assertIsNone(self.published()[1]['expires_at'])

    def test_clear_persists_and_invalid_date_does_not_change_state(self):
        service.action(1, 'metadata', {'plan_label': 'PRO', 'expires_at': 1791460740})
        service.action(1, 'metadata', {'plan_label': 'PRO', 'expires_at': None})
        service.initialize()
        service.publish()
        self.assertIsNone(self.published()[0]['expires_at'])
        before = copy.deepcopy(service.MODEL)
        for invalid in ('invalid', True, 0, 1791460740000):
            with self.assertRaises(ValueError):
                service.action(1, 'metadata', {'expires_at': invalid})
            self.assertEqual(service.MODEL, before)
