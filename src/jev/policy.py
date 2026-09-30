"""Fresh observations and independent confidence/probability gates."""
from dataclasses import asdict, dataclass, field
import logging
import time

from .models import Choice


@dataclass(frozen=True)
class Observation:
    state: dict
    source: str = 'opencv_ocr'
    quality: float = 0
    observed_at: float = field(default_factory=time.time)

    def usable(self, settings):
        age = time.time() - self.observed_at
        return 0 <= age <= settings.max_age_seconds and settings.min_quality <= self.quality <= 1


class DecisionService:
    def __init__(self, client, emit=None):
        self.client = client
        self.settings = client.settings
        self.emit = emit or (lambda event: logging.getLogger('jev').info('%s', event))

    def record(self, event, **values):
        try:
            self.emit({'event': event, 'timestamp': time.time(), 'mode': self.settings.mode, **values})
        except Exception:
            logging.getLogger('jev').warning('Could not record Jev event')

    def choose(self, kind, observation, options, legacy, instructions=None):
        if legacy not in options:
            raise ValueError('Legacy choice must be executable')
        if self.settings.mode == 'off':
            return legacy
        started = time.monotonic()
        reason, answer = None, None
        attempted = False
        cost_before = self.client.cost_usd
        result = legacy
        if not observation.usable(self.settings):
            reason = 'unreliable_or_stale_observation'
        elif len(options) < 2:
            reason = 'single_option'
        else:
            state = {**observation.state, 'objective': self.settings.objective}
            questions = {'action': {'type': 'choice', 'instructions': instructions or f'Choose the best {kind} for state.objective using only the observed facts. Unknown fields are unknown, not zero. Choose only an executable alternative.', 'criteria': options}}
            attempted = True
            answers = self.client.decide(state, questions)
            answer = answers.get('action') if answers else None
            if not isinstance(answer, Choice) or answer.value not in options:
                reason = self.client.last_error or 'invalid_answer'
            elif not observation.usable(self.settings):
                reason = 'observation_expired'
            elif answer.confidence < self.settings.min_confidence or answer.probability < self.settings.min_probability:
                reason = 'low_confidence_or_probability'
            elif self.settings.mode == 'shadow':
                reason = 'shadow'
            else:
                result = answer.value
        self.record('decision', kind=kind, observation=asdict(observation), answer=asdict(answer) if isinstance(answer, Choice) else None, legacy=legacy, selected=result, fallback_reason=reason, duration_seconds=time.monotonic() - started, usage=self.client.last_usage if attempted else None, served_model=self.client.last_model if attempted else None,
            accounted_cost_usd=self.client.cost_usd-cost_before if attempted else 0)
        return result
