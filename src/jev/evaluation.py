"""Summarize observed decisions; offered loot is never treated as earned loot."""
from collections import defaultdict
import math


def _numeric(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and value >= 0


def summarize(events):
    groups = defaultdict(list)
    for event in events:
        if isinstance(event, dict) and event.get('mode') in {'off', 'shadow', 'active'}:
            groups[event['mode']].append(event)
    result = {}
    for mode, rows in groups.items():
        decisions = [e for e in rows if e.get('event') == 'decision']
        searches = [e['search_seconds'] for e in rows if e.get('event') == 'base_selected' and _numeric(e.get('search_seconds'))]
        charges = [(e.get('usage') or {}).get('cost') for e in decisions]
        unknown = [e.get('accounted_cost_usd', 0) for e in decisions if not _numeric((e.get('usage') or {}).get('cost'))]
        battles = [e for e in rows if e.get('event') == 'battle_outcome' and _numeric(e.get('duration_seconds')) and e['duration_seconds'] > 0 and isinstance(e.get('loot'), dict)]
        report = {
            'decisions': len(decisions),
            'api_cost_usd': sum(c for c in charges if _numeric(c)),
            'unknown_charge_reservations_usd': sum(c for c in unknown if _numeric(c)),
            'fallbacks': sum(e.get('fallback_reason') not in (None, 'shadow', 'single_option') for e in decisions),
            'successful_upgrades': sum(e.get('event') == 'upgrade_outcome' and e.get('success') is True for e in rows),
            'unverified_upgrades': sum(e.get('event') == 'upgrade_outcome' and e.get('success') is None for e in rows),
            'mean_search_seconds': sum(searches)/len(searches) if searches else None,
            'labeled_battles': len(battles),
        }
        for resource in ('gold', 'elixir', 'dark_elixir'):
            measured = [e for e in battles if _numeric(e['loot'].get(resource))]
            minutes = sum(e['duration_seconds'] for e in measured)/60
            report[resource+'_per_minute'] = sum(e['loot'][resource] for e in measured)/minutes if minutes else None
        result[mode] = report
    return result
