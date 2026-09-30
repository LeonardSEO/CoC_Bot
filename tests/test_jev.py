import copy
import json
import math
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from jev.client import JevClient, Settings
from jev.models import Choice, Noul, Score, InvalidAnswer, parse_answers
from jev.policy import DecisionService, Observation


QUESTIONS = {
    'action': {'type': 'choice', 'instructions': 'Choose', 'criteria': {'attack': 'Fight', 'skip': 'Next'}},
    'worth': {'type': 'noul', 'instructions': 'Worth it?', 'criteria': {'true': 'Good', 'false': 'Bad'}},
    'value': {'type': 'score', 'instructions': 'Value', 'criteria': ['Low', 'High']},
}
ANSWERS = {
    'action': {'type': 'choice', 'choice': 'attack', 'confidence': .67, 'probabilities': {'attack': .78, 'skip': .22}},
    'worth': {'type': 'noul', 'noul': .96},
    'value': {'type': 'score', 'score': .99, 'confidence': .99, 'probabilities': {'0': .01, '1': .99}, 'legend': {'0': 'Low', '1': 'High'}},
}


def response(answers=None, cost=.00002):
    result = Mock()
    result.status_code = 200
    result.json.return_value = {'answers': copy.deepcopy(ANSWERS if answers is None else answers), 'usage': {'cost': cost}, 'model': 'typesafe/jev-1.13-20260917'}
    result.iter_content.side_effect = lambda **kw: iter([json.dumps(result.json.return_value).encode()])
    result.raise_for_status.return_value = None
    return result


class AnswerTests(unittest.TestCase):
    def test_documented_types_and_distinct_confidence(self):
        result = parse_answers(QUESTIONS, ANSWERS)
        self.assertIsInstance(result['action'], Choice)
        self.assertEqual(result['action'].confidence, .67)
        self.assertEqual(result['action'].probability, .78)
        self.assertIsInstance(result['worth'], Noul)
        self.assertEqual(result['worth'].probability, .96)
        self.assertIsInstance(result['value'], Score)
        self.assertEqual(result['value'].value, .99)

    def test_reject_invalid_or_missing_answers(self):
        for key, field, value in [('action', 'choice', 'invented'), ('action', 'confidence', math.nan), ('worth', 'noul', True), ('worth', 'noul', 1.1), ('value', 'score', -1), ('action', 'type', 'noul')]:
            with self.subTest(field=field, value=value):
                bad = copy.deepcopy(ANSWERS)
                bad[key][field] = value
                with self.assertRaises(InvalidAnswer):
                    parse_answers(QUESTIONS, bad)
        with self.assertRaises(InvalidAnswer):
            parse_answers(QUESTIONS, {})

    def test_reject_distribution_with_wrong_keys_or_total(self):
        for dist in [{'attack': .4, 'skip': .4}, {'attack': 1}, {'attack': .8, 'skip': .2, 'invented': 0}]:
            bad = copy.deepcopy(ANSWERS)
            bad['action']['probabilities'] = dist
            with self.assertRaises(InvalidAnswer):
                parse_answers(QUESTIONS, bad)


class ClientTests(unittest.TestCase):
    def client(self, **kwargs):
        session = Mock()
        session.post.return_value = response()
        settings = Settings(mode='active', max_calls=2, max_cost_usd=.02, reserve_cost_usd=.01, **kwargs)
        return JevClient(settings, api_key='test-secret', session=session), session

    def test_endpoint_payload_and_cost(self):
        client, session = self.client()
        self.assertIsNotNone(client.decide({'gold': 100}, QUESTIONS))
        args, kw = session.post.call_args
        self.assertEqual(args[0], 'https://openrouter.ai/api/alpha/decisions')
        self.assertEqual(kw['json']['model'], 'typesafe/jev-1.13')
        self.assertEqual(kw['json']['state'], {'gold': 100})
        self.assertEqual(kw['timeout'], (1, 2))
        self.assertAlmostEqual(client.cost_usd, .00002)

    def test_call_limit_includes_failed_calls(self):
        client, session = self.client()
        client.decide({}, QUESTIONS)
        client.decide({}, QUESTIONS)
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(session.post.call_count, 2)

    def test_cost_limit_prevents_next_request(self):
        client, session = self.client()
        session.post.return_value = response(cost=.015)
        client.decide({}, QUESTIONS)
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(session.post.call_count, 1)

    def test_error_cools_down_and_reserves_unknown_charge(self):
        client, session = self.client()
        session.post.side_effect = TimeoutError('secret must not be logged')
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(client.last_error, 'api_error:TimeoutError')
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(session.post.call_count, 1)
        self.assertEqual(client.cost_usd, .01)
        self.assertEqual(client.last_error, 'cooldown')

    def test_malformed_answer_still_accounts_usage(self):
        client, session = self.client()
        session.post.return_value = response(answers={})
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertAlmostEqual(client.cost_usd, .00002)

    def test_rate_limit_and_missing_usage_fall_back(self):
        client, session = self.client()
        session.post.return_value.status_code = 429
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(client.last_error, 'http_429')
        client, session = self.client()
        session.post.return_value.json.return_value = {'answers': ANSWERS}
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(client.cost_usd, .01)

    def test_off_missing_key_and_large_state_do_not_call(self):
        for settings, key in [(Settings(), 'secret'), (Settings(mode='active'), '')]:
            session = Mock()
            self.assertIsNone(JevClient(settings, api_key=key, session=session).decide({}, QUESTIONS))
            session.post.assert_not_called()
        client, session = self.client(max_request_bytes=100)
        self.assertIsNone(client.decide({'text': 'x' * 101}, QUESTIONS))
        session.post.assert_not_called()

    def test_key_only_from_environment_and_old_config_defaults(self):
        with patch.dict(os.environ, {'OPENROUTER_API_KEY': 'env-secret'}):
            settings = Settings.from_config(SimpleNamespace())
            self.assertEqual(settings.mode, 'off')
            client = JevClient(settings, session=Mock())
            self.assertNotIn('env-secret', repr(client))
        with self.assertRaises(ValueError):
            Settings(mode='typo')

    def test_reject_bad_model_and_limit_types(self):
        for values in [{'model': 42}, {'mode': []}, {'max_calls': True}, {'max_age_seconds': float('nan')}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values)

    def test_total_deadline_returns_without_waiting_for_slow_transport(self):
        client, session = self.client(total_timeout=.03)
        def slow(*args, **kwargs):
            time.sleep(.2)
            return response()
        session.post.side_effect = slow
        started = time.monotonic()
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertLess(time.monotonic()-started, .15)
        self.assertEqual(client.last_error, 'api_error:TimeoutError')
        self.assertEqual(client.cost_usd, .01)
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(session.post.call_count, 1)

    def test_response_size_is_bounded(self):
        client, session = self.client(max_response_bytes=100)
        self.assertIsNone(client.decide({}, QUESTIONS))
        self.assertEqual(client.cost_usd, .01)
        session.post.return_value.close.assert_called()


class PolicyTests(unittest.TestCase):
    def service(self, mode='active', confidence=.9, probability=.95):
        client = Mock()
        client.settings = Settings(mode=mode)
        client.last_error = None
        client.cost_usd = .001
        client.decide.return_value = {'action': Choice('skip', confidence, {'attack': 1 - probability, 'skip': probability})}
        return DecisionService(client), client

    def test_active_uses_both_thresholds(self):
        obs = Observation({'gold': 100}, source='test', quality=1)
        for confidence, probability, expected in [(.9, .95, 'skip'), (.2, .95, 'attack'), (.9, .55, 'attack')]:
            service, _ = self.service(confidence=confidence, probability=probability)
            self.assertEqual(service.choose('base', obs, {'attack': 'Fight', 'skip': 'Next'}, 'attack'), expected)

    def test_shadow_always_returns_legacy_choice(self):
        service, client = self.service(mode='shadow')
        self.assertEqual(service.choose('base', Observation({}, quality=1), {'attack': 'Fight', 'skip': 'Next'}, 'attack'), 'attack')
        client.decide.assert_called_once()

    def test_bad_observations_and_off_never_call(self):
        for obs in [Observation({}, quality=.1), Observation({}, observed_at=0, quality=1)]:
            service, client = self.service()
            self.assertEqual(service.choose('base', obs, {'attack': 'Fight', 'skip': 'Next'}, 'attack'), 'attack')
            client.decide.assert_not_called()
        service, client = self.service(mode='off')
        service.choose('base', Observation({}, quality=1), {'attack': 'Fight'}, 'attack')
        client.decide.assert_not_called()

    def test_answer_that_arrives_after_observation_expires_falls_back(self):
        service, client = self.service()
        obs = Observation({}, observed_at=100, quality=1)
        times = iter([101, 200])
        with patch('jev.policy.time.time', side_effect=lambda: next(times, 200)):
            self.assertEqual(service.choose('base', obs, {'attack': 'Fight', 'skip': 'Next'}, 'attack'), 'attack')
        client.decide.assert_called_once()


if __name__ == '__main__':
    unittest.main()
