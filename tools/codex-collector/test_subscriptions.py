import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import subscriptions as sub


def jwt(claims):
    return 'header.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.signature'


class SubscriptionClientTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.auth = {'tokens': {'account_id':'selected', 'access_token':jwt({sub.AUTH_CLAIM:{'chatgpt_account_id':'selected'}}),
                               'refresh_token':'fixture-only'}}
        self.save()
        self.primary = {'plan_type':'prolite', 'active_until':'2026-10-20T08:48:38Z',
                        'is_active':True, 'will_renew':True, 'is_delinquent':False}
        self.entitlement = {'subscription_plan':'chatgptprolite', 'renews_at':'2026-10-20T08:48:38Z',
                            'expires_at':'2026-10-20T14:48:38+00:00', 'has_active_subscription':True}
        self.checked = {'accounts':{'selected':{'account':{'account_id':'selected'}, 'entitlement':self.entitlement}}}

    def save(self):
        (self.home/'auth.json').write_text(json.dumps(self.auth))

    def test_live_cycle_and_entitlement_expiry_are_separate(self):
        before = (self.home/'auth.json').read_bytes()
        with patch.object(sub, 'request', side_effect=[self.primary,self.checked]):
            result = sub.fetch(self.home, 1790940000)
        self.assertEqual(result['cycle_ends_at'], 1792486118)
        self.assertEqual(result['entitlement_ends_at']-result['cycle_ends_at'], 21600)
        self.assertTrue(result['will_renew'])
        self.assertEqual(result['source'], 'subscriptions')
        self.assertEqual((self.home/'auth.json').read_bytes(), before)

    def test_account_check_fallback_uses_selected_workspace_and_renews_at(self):
        self.checked['accounts']['another'] = {'account':{'account_id':'another'}, 'entitlement':{'subscription_plan':'chatgptpro'}}
        with patch.object(sub, 'request', side_effect=[sub.SubscriptionError('forbidden'),self.checked]):
            result = sub.fetch(self.home, 1790940000)
        self.assertEqual(result['plan_code'], 'chatgptprolite')
        self.assertEqual(result['cycle_ends_at'], 1792486118)
        self.assertIsNone(result['will_renew'])
        self.assertEqual(result['source'], 'account_check')

    def test_other_paid_workspace_cannot_supply_subscription(self):
        self.checked['accounts'] = {'another':{'account':{'account_id':'another'}, 'entitlement':self.entitlement}}
        with patch.object(sub, 'request', side_effect=[sub.SubscriptionError('forbidden'),self.checked]):
            with self.assertRaises(sub.SubscriptionError): sub.fetch(self.home, 1790940000)

    def test_successful_primary_survives_secondary_error(self):
        with patch.object(sub, 'request', side_effect=[self.primary,sub.SubscriptionError('network')]):
            result = sub.fetch(self.home, 1790940000)
        self.assertEqual(result['status'], 'ok')
        self.assertIsNone(result['entitlement_ends_at'])

    def test_id_token_is_cached_and_uses_claim_observation_time(self):
        self.auth['tokens']['id_token'] = jwt({'exp':1790000000, 'iat':1789900000, sub.AUTH_CLAIM:{
            'chatgpt_account_id':'selected', 'chatgpt_plan_type':'plus',
            'chatgpt_subscription_active_until':'2026-10-09T02:34:46Z',
            'chatgpt_subscription_last_checked':'2026-09-25T00:00:00Z'}})
        self.save()
        result = sub.token_cache(self.home)
        self.assertEqual(result['status'], 'cached')
        self.assertEqual(result['cycle_ends_at'], 1791513286)
        self.assertEqual(result['updated_at'], 1790294400)
        self.assertIsNone(result['will_renew'])

    def test_timestamps_require_offset_and_unix_seconds(self):
        for value in ['2026-10-09T02:34:46', True, 1791513286000, 0, 'bad']:
            with self.assertRaises(sub.SubscriptionError): sub.timestamp(value)
        self.assertEqual(sub.timestamp('2026-10-09T10:34:46+08:00'), 1791513286)

    def test_request_headers_and_http_error_do_not_expose_response_or_token(self):
        seen = []
        class Client:
            def open(self, request, timeout):
                seen.append(request)
                raise urllib.error.HTTPError(request.full_url,403,'private message',{},BytesIO(b'private body'))
        with patch.object(sub.urllib.request,'build_opener',return_value=Client()):
            with self.assertRaises(sub.SubscriptionError) as caught:
                sub.request('fixture-token',sub.SUBSCRIPTIONS,{'account_id':'selected'})
        self.assertEqual(str(caught.exception),'forbidden')
        self.assertEqual(seen[0].get_header('X-openai-target-path'),sub.SUBSCRIPTIONS)
        self.assertEqual(seen[0].get_header('X-openai-target-route'),sub.SUBSCRIPTIONS)
        self.assertIsNone(seen[0].get_header('Cookie'))
        self.assertIsNone(sub.NoRedirect().redirect_request(None,None,302,'',{},'https://other.test'))

    def test_plan_aliases_and_unknown_future_plan(self):
        for raw in ('prolite','chatgptprolite','codex-pro-5x'):
            self.assertEqual(sub.plan_name(raw),'PRO 5X')
        self.assertEqual(sub.plan_name('chatgptplusplan'),'PLUS')
        self.assertEqual(sub.plan_name('new-plan'),'NEW-PLAN')
