"""Validate the Decisions API contract without interpreting generated text."""
from dataclasses import dataclass
import math


class InvalidAnswer(ValueError):
    pass


def number(value, low=0, high=1):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise InvalidAnswer('Invalid numeric value')
    return float(value)


def distribution(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise InvalidAnswer('Invalid probability keys')
    result = {key: number(probability) for key, probability in value.items()}
    if abs(sum(result.values()) - 1) > .02:
        raise InvalidAnswer('Probabilities must sum to one')
    return result


@dataclass(frozen=True)
class Choice:
    value: str
    confidence: float
    probabilities: dict[str, float]

    @property
    def probability(self):
        return self.probabilities[self.value]


@dataclass(frozen=True)
class Noul:
    probability: float


@dataclass(frozen=True)
class Score:
    value: float
    confidence: float
    probabilities: dict[str, float]
    legend: dict[str, str]


def validate_questions(questions):
    if not isinstance(questions, dict) or not questions:
        raise InvalidAnswer('Questions must be a nonempty object')
    for name, question in questions.items():
        if not isinstance(name, str) or not isinstance(question, dict) or not isinstance(question.get('instructions'), str):
            raise InvalidAnswer('Invalid question')
        kind, criteria = question.get('type'), question.get('criteria')
        if kind == 'score':
            valid = isinstance(criteria, list) and len(criteria) >= 2 and all(isinstance(item, str) and item for item in criteria)
        else:
            valid = isinstance(criteria, dict) and bool(criteria) and all(isinstance(k, str) and k and isinstance(v, str) and v for k, v in criteria.items())
            if kind == 'noul':
                valid = valid and set(criteria) == {'true', 'false'}
            elif kind != 'choice':
                valid = False
        if not valid:
            raise InvalidAnswer('Invalid question criteria')


def parse_answers(questions, answers):
    validate_questions(questions)
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise InvalidAnswer('Missing or unexpected answers')
    result = {}
    for name, question in questions.items():
        answer = answers[name]
        kind = question['type']
        if not isinstance(answer, dict) or answer.get('type') != kind:
            raise InvalidAnswer('Wrong answer type')
        try:
            if kind == 'choice':
                probabilities = distribution(answer['probabilities'], question['criteria'])
                if not isinstance(answer['choice'], str) or answer['choice'] not in probabilities:
                    raise InvalidAnswer('Unknown choice')
                result[name] = Choice(answer['choice'], number(answer['confidence']), probabilities)
            elif kind == 'noul':
                result[name] = Noul(number(answer['noul']))
            else:
                legend = {str(i): text for i, text in enumerate(question['criteria'])}
                if answer['legend'] != legend:
                    raise InvalidAnswer('Wrong score legend')
                result[name] = Score(number(answer['score'], high=len(legend) - 1), number(answer['confidence']), distribution(answer['probabilities'], legend), legend)
        except (KeyError, TypeError) as exc:
            raise InvalidAnswer('Incomplete answer') from exc
    return result
