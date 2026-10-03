"""Automatic subscription migration, isolation and publication without real OAuth."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import service
import subscriptions


def observed(at):
    sub = subscriptions.empty()
    sub.update(plan_code='prolite', cycle_ends_at=1792486118, active=True, will_renew=True,
               updated_at=at, source='subscriptions', status='ok')
    return sub


class AutomaticSubscriptionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        patches = patch.multiple(service, STATE=root/'state', PUBLIC=root/'public', MODEL={}, LOGINS={})
        patches.start()
        self.addCleanup(patches.stop)
        service.initialize()
        service.MODEL['enabled'] = True
        for number in (1, 2):
            slot = service.slot_at(number)
            slot.update(bound=True, email=f'test{number}@example.com', plan='PRO 5X', state='ok',
                        snapshot={'id': f'codex-slot-{number}', 'name': f'test{number}@example.com',
                                  'plan': 'PRO 5X', 'updated_at': service.now(), 'expires_at': None,
                                  'reset_credits': 2, 'status': 'ok', 'windows': []})

    def published(self):
        return json.loads((service.PUBLIC/'ai-accounts.json').read_text())

    def test_migration_discards_manual_fields_and_preserves_authorization(self):
        home = service.STATE/'account-1'
        home.mkdir()
        token_file = home/'auth.json'
        token_file.write_text('{"tokens":{"refresh_token":"fixture-only"}}')
        old = token_file.read_bytes()
        slot = service.slot_at(1)
        slot.update(plan_label='custom manual plan', expires_at=1799164740)
        slot['snapshot']['expires_at'] = 1799164740
        service.MODEL['version'] = 1
        service.persist()
        service.initialize()
        self.assertEqual(token_file.read_bytes(), old)
        self.assertTrue(service.slot_at(1)['bound'])
        self.assertNotIn('plan_label', service.slot_at(1))
        self.assertNotIn('expires_at', service.slot_at(1))
        published = self.published()
        self.assertEqual(published['schema_version'], 2)
        self.assertNotIn('expires_at', published['accounts'][0])
        self.assertIsNone(published['accounts'][0]['subscription']['cycle_ends_at'])
        with self.assertRaises(ValueError):
            service.action(1, 'metadata', {'expires_at': 1799164740})

    def test_subscription_failure_keeps_successful_quota_and_cached_date(self):
        slot = service.slot_at(1)
        at = service.now()-100
        slot['subscription'] = observed(at)
        before = copy.deepcopy(slot['snapshot'])
        with patch.object(subscriptions, 'fetch', side_effect=subscriptions.SubscriptionError('forbidden')):
            service.refresh_subscription(slot, service.STATE/'account-1')
        service.publish()
        self.assertEqual(slot['snapshot'], before)
        self.assertEqual(slot['state'], 'ok')
        self.assertEqual(slot['subscription']['cycle_ends_at'], 1792486118)
        self.assertEqual(slot['subscription']['status'], 'cached')
        self.assertEqual(slot['subscription']['updated_at'], at)
        self.assertGreater(slot['subscription_next_attempt'], service.now())
        self.assertEqual(self.published()['accounts'][0]['status'], 'ok')

    def test_success_survives_restart_and_other_slot_is_unchanged(self):
        other = copy.deepcopy(service.slot_at(2))
        with patch.object(subscriptions, 'fetch', return_value=observed(service.now())):
            service.refresh_subscription(service.slot_at(1), service.STATE/'account-1')
        service.persist()
        self.assertEqual(service.slot_at(2), other)
        service.initialize()
        self.assertEqual(self.published()['accounts'][0]['plan'], 'PRO 5X')
        self.assertEqual(self.published()['accounts'][0]['subscription']['cycle_ends_at'], 1792486118)
        self.assertNotIn('subscription_next_attempt', service.public_state()['slots'][0])

    def test_cli_closes_before_http_and_quota_survives_http_401(self):
        slot = service.slot_at(1)
        slot['next_attempt'] = 0
        closed = []
        class FakeRPC:
            def __init__(self, home): pass
            def close(self): closed.append(True)
            def call(self, method, *args):
                if method == 'account/read':
                    return {'account': {'type':'chatgpt', 'email':slot['email'], 'planType':'prolite'}}
                return {'rateLimitsByLimitId':{'codex':{'planType':'prolite', 'primary':{
                    'usedPercent':20, 'windowDurationMins':300, 'resetsAt':1792486118}}}}
        def fetch(home, at):
            self.assertEqual(closed, [True])
            raise subscriptions.SubscriptionError('unauthorized')
        with patch.object(service, 'CodexRPC', FakeRPC), patch.object(subscriptions, 'fetch', fetch):
            service.sync_slot(1)
        self.assertEqual(slot['state'], 'ok')
        self.assertEqual(slot['snapshot']['windows'][0]['remaining_percent'], 80)
        self.assertIsNone(slot['error'])
        self.assertIsNotNone(slot['subscription_error'])

    def test_subscription_success_does_not_hide_quota_failure(self):
        slot = service.slot_at(1)
        slot['next_attempt'] = 0
        with (patch.object(service, 'CodexRPC', side_effect=RuntimeError('connection timeout')),
              patch.object(subscriptions, 'fetch', return_value=observed(service.now()))):
            service.sync_slot(1)
        self.assertEqual(slot['state'], 'error')
        self.assertEqual(slot['subscription']['status'], 'ok')
        self.assertEqual(self.published()['accounts'][0]['status'], 'refresh_error')

    def test_subscription_only_retry_keeps_quota_schedule_and_status(self):
        slot = service.slot_at(1)
        quota_next = slot['next_attempt'] = service.now()+900
        class FakeRPC:
            def __init__(self, home): pass
            def close(self): pass
            def call(self, method, *args):
                if method != 'account/read': raise AssertionError('Quota queried before due')
                return {'account': {'type':'chatgpt', 'email':slot['email']}}
        with patch.object(service, 'CodexRPC', FakeRPC), patch.object(subscriptions, 'fetch', return_value=observed(service.now())):
            service.sync_slot(1)
        self.assertEqual(slot['state'], 'ok')
        self.assertEqual(slot['next_attempt'], quota_next)
