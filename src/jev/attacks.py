"""Bounded scouting and executable deployment choices; no device dependencies."""
from dataclasses import dataclass
import math
import time

from .policy import Observation


@dataclass(frozen=True)
class DeploymentPlan:
    name: str
    points: tuple[tuple[float, float], ...]

    def __post_init__(self):
        if self.name not in {'legacy', 'concentrated', 'distributed'} or not self.points:
            raise ValueError('Invalid deployment plan')
        if any(not math.isfinite(x) or not math.isfinite(y) or not 0 < x < 1 or not 0 < y <= .8 for x, y in self.points):
            raise ValueError('Deployment point outside battlefield')


LEGACY_PLAN = DeploymentPlan('legacy', ((.5, .8),))


def choose_deployment(service, observation, plans, cards):
    if not service.settings.deployment or service.settings.mode == 'off' or observation is None:
        return LEGACY_PLAN
    valid = {'legacy': LEGACY_PLAN, **{plan.name: plan for plan in plans}}
    state = {**observation.state, 'cards': [card for card in cards if card.get('enabled')],
        'plans': {name: {'points': plan.points} for name, plan in valid.items()}}
    if not state['cards']:
        return LEGACY_PLAN
    obs = Observation(state, observation.source, observation.quality, observation.observed_at)
    options = {name: {'legacy': 'Keep the original single deployment position.', 'concentrated': 'Deploy at one freshly validated legal position.', 'distributed': 'Spread troop cards across freshly validated legal positions.'}[name] for name in valid}
    name = service.choose('deployment', obs, options, 'legacy',
        'Choose an executable deployment plan for state.objective using only the recognized card categories and legal points. Troop identities and defenses are unknown. Prefer legacy when the other plans have no demonstrated advantage. Spell targeting is unchanged.')
    return valid[name]


def select_base(service, observer, get_frame, click_next, *, sleep=time.sleep):
    settings = service.settings
    if settings.mode == 'off' or not settings.base_selection:
        return
    started = time.monotonic()
    deadline = started + settings.max_search_seconds
    skipped = 0
    current = observer.scout(get_frame())
    while current is not None and time.monotonic() < deadline and skipped < settings.max_skips:
        obs = Observation({**current.state, 'search_seconds': time.monotonic()-started, 'bases_skipped': skipped}, current.source, current.quality, current.observed_at)
        action = service.choose('base', obs, {'attack': 'Attack this base with the current army.', 'skip': 'Pay the observed search cost and inspect another base.'}, 'attack',
            'For state.objective, choose attack or skip. Compare observed available loot with the search cost and time already spent. Defenses and army strength are unknown; do not infer them. Prefer attack as the search limit approaches.')
        if action != 'skip' or time.monotonic() >= deadline:
            break
        # Revalidate both scouting controls and base identity after the API call.
        fresh = observer.scout(get_frame())
        if fresh is None or not fresh.usable(settings) or fresh.state['signature'] != current.state['signature'] or fresh.state['loot'] != current.state['loot']:
            service.record('fallback', kind='base', reason='scouting_changed')
            break
        if time.monotonic() >= deadline:
            break
        click_next(*fresh.state['next_position'])
        skipped += 1
        service.record('base_skip', signature=fresh.state['signature'], search_cost=fresh.state['search_cost'])
        current = None
        # A successful tap is not proof that matchmaking produced a new base.
        while time.monotonic() < deadline:
            sleep(.1)
            candidate = observer.scout(get_frame())
            if candidate is not None and candidate.state['signature'] != fresh.state['signature']:
                current = candidate
                break
    service.record('base_selected', bases_skipped=skipped, search_seconds=time.monotonic()-started,
        loot_available=current.state['loot'] if current else None, fallback_reason='vision_unavailable_or_search_limit' if current is None else None)
