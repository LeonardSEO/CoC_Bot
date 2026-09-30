"""Bounded OpenRouter transport. Failed requests are never automatically retried."""
from dataclasses import dataclass, fields
import json
import os
import queue
import threading
import time

from .models import number, parse_answers, validate_questions


@dataclass(frozen=True)
class Settings:
    mode: str = 'off'
    model: str = 'typesafe/jev-1.13'
    objective: str = 'farm_and_upgrade'
    upgrades: bool = True
    base_selection: bool = False
    deployment: bool = False
    min_confidence: float = .70
    min_probability: float = .80
    min_quality: float = .80
    max_age_seconds: float = 5
    connect_timeout: float = 1
    read_timeout: float = 2
    total_timeout: float = 3
    max_calls: int = 1000
    max_cost_usd: float = 1
    reserve_cost_usd: float = .01
    max_request_bytes: int = 32000
    max_response_bytes: int = 128000
    cooldown_seconds: float = 60
    max_skips: int = 10
    max_search_seconds: float = 25

    def __post_init__(self):
        if not isinstance(self.mode, str) or self.mode not in {'off', 'shadow', 'active'}:
            raise ValueError('JEV_MODE must be off, shadow or active')
        if not isinstance(self.objective, str) or self.objective not in {'farm_and_upgrade', 'trophies'} or not isinstance(self.model, str) or not self.model:
            raise ValueError('Invalid Jev objective or model')
        for name in ('min_confidence', 'min_probability', 'min_quality'):
            number(getattr(self, name))
        for name in ('max_age_seconds', 'connect_timeout', 'read_timeout', 'total_timeout', 'max_cost_usd', 'reserve_cost_usd', 'cooldown_seconds', 'max_search_seconds'):
            number(getattr(self, name), 0.000001, float('inf'))
        for name in ('max_calls', 'max_request_bytes', 'max_response_bytes', 'max_skips'):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('Invalid Jev limit')
        for name in ('upgrades', 'base_selection', 'deployment'):
            if not isinstance(getattr(self, name), bool):
                raise ValueError('Jev feature switches must be boolean')

    @classmethod
    def from_config(cls, config):
        return cls(**{field.name: getattr(config, 'JEV_' + field.name.upper(), field.default) for field in fields(cls)})


class JevClient:
    endpoint = 'https://openrouter.ai/api/alpha/decisions'

    def __init__(self, settings, *, api_key=None, session=None):
        self.settings = settings
        self._api_key = os.environ.get('OPENROUTER_API_KEY', '') if api_key is None else api_key
        self._session = session
        self._lock = threading.Lock()
        self.calls = 0
        self.cost_usd = 0.0
        self.last_error = None
        self.last_usage = None
        self.last_model = None
        self._resume_at = 0
        self._inflight = threading.Event()

    def _request(self, payload):
        """Return on a wall-clock deadline even if a peer keeps dripping bytes.

        At most one daemon worker can remain in flight. A timed-out worker never
        changes accounting or decisions, and no later request may overlap it.
        """
        deadline = time.monotonic() + self.settings.total_timeout
        result = queue.Queue(maxsize=1)
        self._inflight.set()

        def request():
            response = None
            outcome = None
            try:
                if self._session is None:
                    import requests
                    self._session = requests.Session()
                response = self._session.post(self.endpoint, headers={'Authorization': f'Bearer {self._api_key}', 'Content-Type': 'application/json'}, json=payload,
                    timeout=(self.settings.connect_timeout, self.settings.read_timeout), stream=True)
                if response.status_code != 200:
                    outcome = (True, response.status_code, None)
                else:
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=4096):
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Total request deadline')
                        body.extend(chunk)
                        if len(body) > self.settings.max_response_bytes:
                            raise ValueError('Response too large')
                    outcome = (True, response.status_code, json.loads(body))
            except Exception as exc:
                outcome = (False, exc, None)
            finally:
                if response is not None:
                    try: response.close()
                    except Exception: pass
                self._inflight.clear()
                if outcome is not None: result.put(outcome)

        threading.Thread(target=request, name='jev-request', daemon=True).start()
        try:
            succeeded, status, data = result.get(timeout=max(0, deadline-time.monotonic()))
        except queue.Empty:
            raise TimeoutError('Total request deadline') from None
        if not succeeded:
            raise status
        return status, data

    def decide(self, state, questions):
        with self._lock:
            return self._decide(state, questions)

    def _decide(self, state, questions):
        self.last_usage = self.last_model = None
        self.last_error = None
        if self.settings.mode == 'off' or not self._api_key:
            self.last_error = 'disabled' if self.settings.mode == 'off' else 'missing_api_key'
            return None
        if self._inflight.is_set():
            self.last_error = 'request_in_flight'
            return None
        if time.monotonic() < self._resume_at:
            self.last_error = 'cooldown'
            return None
        if self.calls >= self.settings.max_calls or self.cost_usd + self.settings.reserve_cost_usd > self.settings.max_cost_usd:
            self.last_error = 'budget_exhausted'
            return None
        payload = {'model': self.settings.model, 'state': state, 'questions': questions}
        try:
            validate_questions(questions)
            if not isinstance(state, dict):
                raise ValueError('State must be an object')
            encoded = json.dumps(payload, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError):
            self.last_error = 'invalid_request'
            return None
        if len(encoded) > self.settings.max_request_bytes:
            self.last_error = 'request_too_large'
            return None
        self.calls += 1
        # Unknown charges (timeouts or malformed usage) keep this reservation.
        self.cost_usd += self.settings.reserve_cost_usd
        try:
            status, data = self._request(payload)
            if status != 200:
                self.last_error = f'http_{status}'
                self._resume_at = time.monotonic() + self.settings.cooldown_seconds
                return None
            cost = number(data['usage']['cost'], high=float('inf'))
            self.cost_usd += cost - self.settings.reserve_cost_usd
            self.last_usage = {'cost': cost, 'input_tokens': data['usage'].get('input_tokens'), 'output_tokens': data['usage'].get('output_tokens')}
            self.last_model = data.get('model')
            return parse_answers(questions, data['answers'])
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            # Never log exception messages, response bodies or Authorization.
            self.last_error = f'api_error:{type(exc).__name__}'
            self._resume_at = time.monotonic() + self.settings.cooldown_seconds
            return None
