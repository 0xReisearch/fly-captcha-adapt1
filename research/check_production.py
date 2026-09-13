"""Opt-in real production smoke/evaluation. Read the key without echo; never save it."""
import argparse
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production import ProductionController
from run import experiment
from sensory import LiveEye


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--seed', type=int, default=17)
    args = parser.parse_args()
    key = getpass.getpass('Production API key (hidden): ').strip()
    controller = ProductionController(key)
    del key
    try:
        eye = LiveEye(args.vendor, overview_size=2)
        result = experiment(eye, args.seed, args.output, limit=args.limit, controls=False,
                            controller_factory=lambda: controller)
        print(json.dumps({'metrics': result['metrics'], 'controller_feedbacks': result['controller_feedbacks'],
                          'test_feedback': result['test_feedback'], 'controller_verification': result['controller_verification']}), flush=True)
    finally:
        controller.close()
