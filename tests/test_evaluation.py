import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jev.evaluation import summarize


class EvaluationTests(unittest.TestCase):
    def test_available_loot_is_never_reported_as_earned_loot(self):
        result = summarize([
            {'mode': 'active', 'event': 'base_selected', 'search_seconds': 3, 'loot_available': {'gold': 1000000}},
            {'mode': 'active', 'event': 'decision', 'usage': {'cost': .0001}, 'accounted_cost_usd': .0001, 'fallback_reason': None},
            {'mode': 'active', 'event': 'upgrade_outcome', 'success': True},
        ])['active']
        self.assertIsNone(result['gold_per_minute'])
        self.assertEqual(result['successful_upgrades'], 1)
        self.assertEqual(result['mean_search_seconds'], 3)
        self.assertEqual(result['api_cost_usd'], .0001)

    def test_labeled_outcomes_produce_separate_resource_metrics(self):
        result = summarize([
            {'mode': 'active', 'event': 'battle_outcome', 'duration_seconds': 120, 'loot': {'gold': 400000, 'elixir': 200000, 'dark_elixir': 4000}},
            {'mode': 'off', 'event': 'battle_outcome', 'duration_seconds': 120, 'loot': {'gold': 200000, 'elixir': 100000, 'dark_elixir': 1000}},
            {'mode': 'active', 'event': 'decision', 'usage': None, 'accounted_cost_usd': .01, 'fallback_reason': 'timeout'},
        ])
        self.assertEqual(result['active']['gold_per_minute'], 200000)
        self.assertEqual(result['off']['gold_per_minute'], 100000)
        self.assertEqual(result['active']['dark_elixir_per_minute'], 2000)
        self.assertEqual(result['active']['unknown_charge_reservations_usd'], .01)


if __name__ == '__main__':
    unittest.main()
