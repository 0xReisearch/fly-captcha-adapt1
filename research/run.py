"""Fresh local live-simulation experiments; no production calls or task checkpoint."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import resource
import subprocess
import time
import threading

from PIL import Image

from circuit import FlyAgent
from sensory import LiveEye

ROOT = Path(__file__).resolve().parents[1]


def dataset():
    tiles = json.loads((ROOT / 'data/tiles.json').read_text())['tiles']
    for tile in tiles:
        assert hashlib.sha256((ROOT / 'data/tiles' / (tile['id']+'.jpg')).read_bytes()).hexdigest() == tile['sha256']
    train = [t for t in tiles if t['split'] == 'training']
    test = [t for t in tiles if t['split'] == 'test']
    assert not {t['sha256'] for t in train} & {t['sha256'] for t in test}
    return train, test


def experiment(eye, seed, directory, core_path=None, limit=None, emit=None, observe=None, stop=None,
               attention_forgetting=.98, attention_epsilon=.3, controls=True, retain=None, controller_factory=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    stop = stop or threading.Event()
    train, test = dataset()
    rng = random.Random(seed)
    rng.shuffle(train)
    rng.shuffle(test)
    if limit:
        train, test = train[:limit], test[:min(limit, 36)]
    fly = FlyAgent(seed, attention_forgetting, attention_epsilon)
    frozen = copy.deepcopy(fly)
    controller = None
    retained = False
    if controller_factory:
        controller = controller_factory()
    elif core_path:
        from controller import LocalController
        controller = LocalController(core_path)
    if controller:
        (directory / 'domain.json').write_text(json.dumps(controller.spec, indent=2)+'\n')
    records = []
    start = time.monotonic()
    initial_simulations = eye.calls
    initial_seconds = eye.seconds
    initial = fly.fingerprint()
    configuration = {'seed': seed, 'overview_size': eye.overview_size,
                     'attention_forgetting': attention_forgetting, 'attention_epsilon': attention_epsilon,
                     'run_controls': controls,
                     'readout': 'recursive_least_squares', 'hidden_units_per_readout': 128,
                     'reward': 'chosen_action_binary_correctness', 'inspection_cost': .02}
    configuration['dataset_manifest_sha256'] = hashlib.sha256((ROOT/'data/tiles.json').read_bytes()).hexdigest()
    configuration['graph_weight_sha256'] = eye.graph_sha256
    if core_path:
        configuration['core_commit'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=core_path, text=True).strip()
    (directory / 'configuration.json').write_text(json.dumps(configuration, indent=2)+'\n')
    before_test = None
    core_before_test = None
    stream = (directory / 'trace.jsonl').open('w')

    def trial(agent, tile, phase, learning=False, erased=False, force=None):
        if stop.is_set():
            raise InterruptedError('Experiment stopped before next observation')
        def budget(context):
            if stop.is_set():
                raise InterruptedError('Experiment stopped before next controller call')
            if force is not None or controller is None:
                return force if force is not None else True, {'policy': 'fixed_inspection', 'decision_id': None}
            return controller.decide(context, learning)
        observations = []
        def capture(observation, counts):
            if stop.is_set():
                raise InterruptedError('Experiment stopped before next neural observation')
            if observe:
                observe(tile['id'], phase, observation, counts)
            observations.append(observation)
        with Image.open(ROOT / 'data/tiles' / (tile['id']+'.jpg')) as image:
            result = agent.act(eye, image, budget, learning, erased, capture)
        # The neural agent has irrevocably selected an action before this label is read.
        reward = int((result['policy'] == 'select') == tile['target'])
        error = None
        if learning:
            if stop.is_set():
                raise InterruptedError('Experiment stopped before feedback')
            error = agent.feedback(result, reward)
            if controller:
                controller.feedback(result, reward)
                if controller.feedback_count % 24 == 0:
                    controller.settle()
        record = {k: v for k, v in result.items() if k not in ('eligibility', 'attention')}
        record.update(phase=phase, tile_id=tile['id'], target=tile['target'], correct=bool(reward),
                      feedback_count=agent.feedback_count, neural=observations[-1],
                      reward_prediction_error=error, index=len(records))
        records.append(record)
        stream.write(json.dumps(record)+'\n')
        stream.flush()
        if emit:
            emit(record)
        return record

    try:
        for tile in test:
            trial(fly, tile, 'before', force=True)
        assert fly.fingerprint() == initial
        for i, tile in enumerate(train):
            trial(fly, tile, 'training', learning=True)
            if (i+1) % 60 == 0:
                print(f'seed={seed} train={i+1}/{len(train)} accuracy={sum(r["correct"] for r in records[-60:])/60:.3f}', flush=True)
        if controller:
            controller.settle()
            core_before_test = controller.fingerprint()
        before_test = fly.fingerprint()
        fixed_attention = copy.deepcopy(fly)
        fixed_attention.attention = copy.deepcopy(frozen.attention)
        phases = [('after', fly, False, None)]
        if controls:
            phases += [('frozen_fly', frozen, False, None),
            ('erased_neural_input', fly, True, None), ('wide_only', fly, False, False),
            ('fixed_inspection', fly, False, True),
            ('frozen_attention', fixed_attention, False, None)]
        for phase, agent, erased, force in phases:
            for tile in test:
                trial(agent, tile, phase, erased=erased, force=force)
        assert fly.fingerprint() == before_test
        assert frozen.fingerprint() == initial
        assert controller is None or controller.fingerprint() == core_before_test
        eye.verify_fixed_graph()
        metrics = {}
        for phase in dict.fromkeys(r['phase'] for r in records):
            rows = [r for r in records if r['phase'] == phase]
            boards = [rows[i:i+9] for i in range(0, len(rows)-8, 9)]
            metrics[phase] = {'tiles': len(rows), 'correct': sum(r['correct'] for r in rows),
                              'accuracy': sum(r['correct'] for r in rows)/len(rows),
                              'inspections': sum(r['inspection'] for r in rows),
                              'boards': len(boards), 'passed_boards': sum(all(r['correct'] for r in b) for b in boards)}
        result = {'seed': seed, 'metrics': metrics, 'fly_feedbacks': fly.feedback_count,
                  'configuration': configuration,
                  'attention_feedbacks': int(fly.attention.updates.sum()),
                  'controller_feedbacks': controller.feedback_count if controller else 0,
                  'initial_fly_sha256': initial, 'frozen_fly_sha256': before_test,
                  'heldout_fly_sha256': fly.fingerprint(), 'heldout_controller_sha256': core_before_test,
                  'graph_fixed': True, 'test_feedback': 0, 'exact_split_overlap': 0,
                  'live_simulations': eye.calls-initial_simulations,
                  'overview_pixels': eye.overview_size,
                  'simulation_seconds': eye.seconds-initial_seconds,
                  'elapsed_seconds': time.monotonic()-start,
                  'process_peak_rss_mb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                  'protocol': 'Fixed biological graph, artificial reward-plastic readouts; one pass training; distinct frozen test images.',
                  'controller': getattr(controller, 'description', 'local Adapt-1 inspection budget') if controller else 'fixed inspection budget',
                  'controller_verification': getattr(controller, 'verification', 'local retained learning state') if controller else None}
        (directory / 'results.json').write_text(json.dumps(result, indent=2)+'\n')
        if retain:
            retain(fly, eye, controller, directory)
            retained = True
        return result
    finally:
        stream.close()
        if controller:
            if not retained:
                controller.close()
            with (directory / 'core-api-trace.jsonl').open('w') as audit:
                for call in controller.calls:
                    audit.write(json.dumps(call)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', required=True)
    parser.add_argument('--core')
    parser.add_argument('--output', required=True)
    parser.add_argument('--seeds', default='17,29,43')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--overview-size', type=int, default=100)
    parser.add_argument('--attention-forgetting', type=float, default=.98)
    parser.add_argument('--attention-epsilon', type=float, default=.3)
    args = parser.parse_args()
    eye = LiveEye(args.vendor, args.overview_size)
    results = []
    for seed in map(int, args.seeds.split(',')):
        result = experiment(eye, seed, Path(args.output)/f'seed-{seed}', args.core, args.limit,
                            attention_forgetting=args.attention_forgetting, attention_epsilon=args.attention_epsilon)
        results.append(result)
        print(json.dumps(result, indent=2), flush=True)
    (Path(args.output)/'summary.json').write_text(json.dumps(results, indent=2)+'\n')


if __name__ == '__main__':
    main()
