#!/usr/bin/env python3
"""Offline comparison of bot event JSONL and optional labeled battle outcomes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jev.evaluation import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', type=Path, nargs='+', help='Event logs and optionally measured battle outcomes')
    parser.add_argument('--instance', help='Restrict the comparison to one instance')
    args = parser.parse_args()
    events = []
    for path in args.files:
        with path.open(encoding='utf-8') as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    parser.error(f'{path}:{line_number}: invalid JSON')
                if not isinstance(event, dict):
                    parser.error(f'{path}:{line_number}: event must be an object')
                if not args.instance or event.get('instance_id') == args.instance:
                    events.append(event)
    print(json.dumps(summarize(events), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
