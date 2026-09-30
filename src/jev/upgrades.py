"""Choose among recognized upgrades, preserving priority and discount groups."""
from dataclasses import asdict, dataclass, field
import time

from .policy import Observation


@dataclass(frozen=True)
class UpgradeCandidate:
    name: str
    x: float
    y: float
    affordable: bool = True
    affordability_source: str = "caller_filtered"
    cost: int | None = None
    resource_balance: int | None = None
    discounted: bool = False
    priority: int = 0
    quality: float = 1
    observed_at: float = field(default_factory=time.time)


def choose_upgrade(service, candidates, legacy, context, availability):
    if not service.settings.upgrades or service.settings.mode == 'off':
        return legacy
    # An unreadable alternative must not silently change the choice set.
    if not candidates or any(c.quality < service.settings.min_quality for c in candidates):
        service.record('fallback', kind='upgrade', reason='unreadable_candidate')
        return legacy
    eligible = [c for c in candidates if c.affordable]
    if not eligible:
        return legacy
    level = min(c.priority for c in eligible)
    eligible = [c for c in eligible if c.priority == level]
    discounted = [c for c in eligible if c.discounted]
    if discounted:
        eligible = discounted
    if legacy not in eligible:
        # The caller supplies its already filtered legacy group.
        return legacy
    options = {f'candidate_{i}': f'Upgrade {c.name}' for i, c in enumerate(eligible)}
    default = f'candidate_{eligible.index(legacy)}'
    state = {'village': context, 'availability': availability, 'candidates': [asdict(c) for c in eligible]}
    observation = Observation(state, source='upgrade_menu', quality=min(c.quality for c in eligible), observed_at=min(c.observed_at for c in eligible))
    chosen = service.choose('upgrade', observation, options, default,
        'Choose the upgrade that best supports state.objective. All candidates are recognized and within the same allowed priority group. Affordability is based on a local menu colour indicator, not a verified numeric cost/balance comparison. Consider offensive progression, farming utility and builder/lab use. Costs, levels and durations not observed are unknown; do not invent them.')
    return eligible[list(options).index(chosen)]
