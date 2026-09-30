"""Runtime wiring and bounded JSONL telemetry, shared by attacker and upgrader."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .client import JevClient, Settings
from .policy import DecisionService


def create_service(config):
    from log import logger, LOG_DIR
    import utils
    try:
        settings = Settings.from_config(config)
    except ValueError:
        logger.error('Invalid Jev configuration; using legacy bot decisions')
        settings = Settings()
    instance = utils.INSTANCE_ID or 'main'
    sink = logging.getLogger(f'jev.events.{instance}')
    sink.setLevel(logging.INFO)
    sink.propagate = False
    if not sink.handlers:
        try:
            Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(Path(LOG_DIR) / f'{instance}.jev.jsonl', maxBytes=5_000_000, backupCount=3, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            sink.addHandler(handler)
        except OSError:
            logger.error('Jev event file unavailable; decisions will still be logged to the bot log')

    def emit(event):
        event = {**event, 'instance_id': instance}
        serialized = json.dumps(event, allow_nan=False, default=str)
        sink.info(serialized)
        logger.info('Jev: {}', serialized)

    client = JevClient(settings)
    if settings.mode != 'off' and not client._api_key:
        logger.warning('OPENROUTER_API_KEY missing; Jev will use legacy decisions')
    return DecisionService(client, emit=emit)
