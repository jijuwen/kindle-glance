import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from app.ai_account_data import validate_snapshot
from app.ai_accounts import account_status, load_snapshot, reset_label, shanghai_time, snapshot_revision


class AiAccountsTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 19, 12, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.at = int(self.now.timestamp())
        self.account = {'id': 'one', 'name': 'a@example.com', 'plan': 'PLUS', 'updated_at': self.at,
                        'expires_at': None, 'reset_credits': None, 'status': 'ok',
                        'windows': [{'label': '5小时', 'remaining_percent': 3, 'reset_at': self.at + 3600}]}
        self.snapshot = {'schema_version': 1, 'collected_at': self.at, 'accounts': [self.account]}

    def test_la_daylight_and_standard_time(self):
        for month, expected in [(9, '09/19 14:46'), (12, '12/19 15:46')]:
            source = datetime(2026, month, 18, 23, 46, tzinfo=ZoneInfo('America/Los_Angeles'))
            self.assertEqual(shanghai_time(source.timestamp()), expected)

    def test_recent_upload_does_not_make_old_quota_fresh(self):
        self.account['updated_at'] -= 3600
        self.assertEqual(account_status(self.account, self.at, self.now), '数据已过期')

    def test_past_reset_is_pending_not_replenished(self):
        self.account['windows'][0]['reset_at'] = self.at - 10
        self.assertIn('待刷新', account_status(self.account, self.at, self.now))
        self.assertIn('待刷新', reset_label(self.at - 10, self.now))
        self.assertEqual(self.account['windows'][0]['remaining_percent'], 3)

    def test_ingest_rejects_credentials_unknown_fields_and_bad_units(self):
        for field, value in [('tokens', {'access_token': 'private'}), ('email', 'other@example.com')]:
            invalid = copy.deepcopy(self.snapshot)
            invalid['accounts'][0][field] = value
            with self.assertRaises(ValueError): validate_snapshot(invalid)
        self.snapshot['collected_at'] *= 1000
        with self.assertRaises(ValueError): validate_snapshot(self.snapshot)

    def test_unknown_percentage_is_preserved_and_nan_rejected(self):
        self.account['windows'][0]['remaining_percent'] = None
        self.assertIsNone(validate_snapshot(self.snapshot)['accounts'][0]['windows'][0]['remaining_percent'])
        self.account['windows'][0]['remaining_percent'] = float('nan')
        with self.assertRaises(ValueError): validate_snapshot(self.snapshot)

    def test_content_change_invalidates_snapshot_and_bad_file_fails_closed(self):
        old = snapshot_revision(self.snapshot)
        self.account['windows'][0]['remaining_percent'] = 20
        self.assertNotEqual(old, snapshot_revision(self.snapshot))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ai-accounts.json'
            path.write_text(json.dumps(self.snapshot), encoding='utf-8')
            self.assertEqual(load_snapshot(path), self.snapshot)
            path.write_text('{broken', encoding='utf-8')
            self.assertIsNone(load_snapshot(path))
