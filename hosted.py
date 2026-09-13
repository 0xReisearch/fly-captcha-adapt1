"""Fixed sensory experiment over the public Domain API. No Core imports or solver."""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import random
import threading
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parent
API = 'https://rei-neuroadapt-api.reilabs.org/api/v1'


def read_tiles():
    manifest = json.loads((ROOT / 'data/tiles.json').read_text())
    tiles = []
    for item in manifest['tiles']:
        vision = json.loads((ROOT / 'data/vision' / (item['id'] + '.json')).read_text())
        if hashlib.sha256((ROOT / 'data/tiles' / (item['id'] + '.jpg')).read_bytes()).hexdigest() != item['sha256'] or vision['image_sha256'] != item['sha256']:
            raise RuntimeError('Sensory asset integrity check failed.')
        features = vision['features']
        if len(features) != 64 or not all(k.startswith('neural_') and isinstance(v, (int, float)) for k, v in features.items()):
            raise RuntimeError('Unexpected sensory feature contract.')
        tiles.append({**item, 'vision': vision})
    train = {x['sha256'] for x in tiles if x['split'] == 'training'}
    test = {x['sha256'] for x in tiles if x['split'] == 'test'}
    if train & test or len(train) != 360 or len(test) != 180:
        raise RuntimeError('Unexpected train/test split.')
    return tiles


def declaration(domain_id, features):
    return {
        'domain_id': domain_id, 'session_id': domain_id,
        'description': 'Learn a two-button visual choice from neural observations and execution feedback.',
        'schema': {'event_types': ['visual_trial'], 'entities': [], 'relations': ['tile_choice'], 'signals': features + ['reward']},
        'hypotheses': [{'name': p, 'relation': 'tile_choice', 'policy': p, 'weight': 1} for p in ('select', 'leave')],
        'learning': {
            'enabled': True,
            'context': {'feature_paths': ['values.' + f for f in features], 'event_types': ['visual_trial'], 'max_samples': 1024},
            'reward': {'components': [{'field': 'values.reward', 'goal': 'maximize', 'min': 0, 'max': 1}]},
            'policy': {'exploration_mode': 'ucb', 'exploration_strength': 0.7, 'min_context_observations': 2,
                       'model_max_weight': 0.45, 'minimum_confidence': 0, 'abstain_on_ood': False,
                       'transfer_strength': 0, 'action_transfer_strength': 0},
            'latent_belief': {'enabled': False},
            'training': {'enabled': True, 'min_samples': 24, 'retrain_interval': 24, 'dimensions': 192, 'epochs': 40},
        },
    }


class RunError(Exception):
    """Only reviewed, credential-free messages cross the UI boundary."""


class RunStopped(RunError):
    """An intentional cancellation, distinct from an API or contract failure."""


class HostedCore:
    def __init__(self, key, features, stop=None, transport=None):
        self.domain_id = 'fly-' + uuid.uuid4().hex
        self.stop = stop or threading.Event()
        self.deadline = time.monotonic() + 7200
        self.client = httpx.Client(base_url=API + '/', headers={'Authorization': 'Bearer ' + key},
                                   timeout=90, trust_env=False, follow_redirects=False, transport=transport)
        self.spec = declaration(self.domain_id, features)
        self.feedback_count = 0
        self.calls = []
        self.trace_bytes = 0

    def call(self, route, body):
        if self.stop.is_set() or time.monotonic() > self.deadline:
            raise RunStopped('Run stopped. Previously accepted feedback remains in your Domain.')
        start = time.monotonic()
        try:
            response = self.client.post(route, json=body)
        except httpx.HTTPError:
            raise RunError('Neuroadapt could not be reached. No automatic retry: a write may already have been accepted.') from None
        if not 200 <= response.status_code < 300:
            self.calls.append({'route': route, 'request': body, 'http_status': response.status_code, 'completion': 'unconfirmed'})
            reason = {401: 'API key rejected.', 403: 'API key lacks access.', 429: 'Neuroadapt rate limit reached.'}.get(response.status_code, 'Neuroadapt rejected this operation.')
            raise RunError(f'{reason} HTTP {response.status_code} on {route.rsplit("/", 1)[-1]}. Run stopped without retrying writes.')
        try:
            result = response.json()
        except ValueError:
            raise RunError('Neuroadapt returned a non-JSON response.') from None
        if not isinstance(result, dict):
            raise RunError('Unexpected Neuroadapt response shape.')
        self.trace_bytes += len(response.content)
        if self.trace_bytes > 64 * 1024 * 1024:
            raise RunError('Run trace exceeded the demo memory budget. Run stopped.')
        # No headers, auth, URLs containing secrets, or transport exceptions are retained.
        self.calls.append({'route': route, 'request': body, 'response': result, 'seconds': time.monotonic() - start})
        return result

    def create(self):
        self.call('domains', self.spec)

    def query(self, features, learning=False, inspect=False):
        body = {'session_id': self.domain_id, 'question': 'Choose the tile action.',
                'relation': 'tile_choice', 'context': {'values': features},
                'selection_mode': 'ucb' if learning else 'exploit', 'allow_exploration': learning, 'top_k': 1,
                'return_fields': ['decision_id', 'selection', 'learning_state', 'ranked_hypotheses', 'policy_scores']}
        if inspect:
            body.pop('return_fields')
        result = self.call(f'domains/{self.domain_id}/' + ('explain' if inspect else 'query'), body)
        if inspect:
            return result
        if not isinstance(result.get('selection'), dict):
            raise RunError('The hosted query route did not expose policy selection.')
        policy = result['selection'].get('selected_policy')
        if policy not in ('select', 'leave', None):
            raise RunError('Neuroadapt returned an action outside the declared contract.')
        return policy, result

    def feedback(self, decision, features, policy, reward):
        if policy is None:
            return
        if not decision.get('decision_id'):
            raise RunError('The hosted query route did not return a decision ID.')
        body = {'session_id': self.domain_id, 'decision_id': decision['decision_id'],
                'feedback_kind': 'execution', 'relation': 'tile_choice', 'policy': policy,
                'outcome': 'success' if reward else 'failure', 'values': {'reward': reward},
                'context': {'values': features}}
        result = self.call(f'domains/{self.domain_id}/feedback', body)
        if not result.get('credit_assignment', {}).get('contextual_learning_applied'):
            raise RunError('Feedback was accepted but not admitted to policy learning. Run stopped.')
        self.feedback_count += 1

    @staticmethod
    def policy_state(response):
        state = response.get('learning_state') or response.get('explanation', {}).get('learning_state') or {}
        policy = state.get('subsystems', {}).get('feedback_policy')
        if not isinstance(policy, dict) or 'sample_count' not in policy or 'model' not in policy:
            raise RunError('The hosted API did not expose the policy state needed to verify learning.')
        return policy

    def settle(self, features):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            policy = self.policy_state(self.query(features, inspect=True))
            if policy['sample_count'] != self.feedback_count:
                if self.stop.wait(2):
                    raise RunStopped('Run stopped.')
                continue
            if policy['model'].get('status') in ('running', 'queued', 'training', 'pending'):
                self.stop.wait(2)
                continue
            return policy
        raise RunError('Policy training/admission did not settle within five minutes.')

    def close(self):
        self.client.headers.pop('Authorization', None)
        self.client.close()


def measured_metrics(rows):
    metrics = {}
    for phase in ('before', 'training', 'after'):
        subset = [r for r in rows if r['phase'] == phase]
        boards = [subset[i:i+9] for i in range(0, len(subset), 9) if len(subset[i:i+9]) == 9]
        metrics[phase] = {'tiles': len(subset), 'correct': sum(r['correct'] for r in subset),
                          'accuracy': sum(r['correct'] for r in subset) / len(subset) if subset else None,
                          'boards': len(boards), 'passed_boards': sum(all(r['correct'] for r in b) for b in boards),
                          'abstentions': sum(r['policy'] is None for r in subset)}
    return metrics


def run_experiment(core, tiles, seed, emit, progress=lambda value: None):
    train = [x for x in tiles if x['split'] == 'training']
    test = [x for x in tiles if x['split'] == 'test']
    rng = random.Random(seed)
    rng.shuffle(train)
    rng.shuffle(test)
    records = []
    try:
        progress('Creating a fresh hosted Domain')
        core.create()
        initial = core.settle(train[0]['vision']['features'])
        if initial['sample_count'] != 0:
            raise RunError('The new Domain is not empty.')
        frozen = None
        for phase, items in [('before', test[:18]), ('training', train), ('after', test)]:
            if phase == 'after':
                progress('Waiting for training to settle')
                frozen = core.settle(train[-1]['vision']['features'])
            for i, tile in enumerate(items):
                progress(f'{phase}: {i+1}/{len(items)}')
                features = tile['vision']['features']
                policy, decision = core.query(features, learning=phase != 'after')
                correct = policy is not None and ((policy == 'select') == tile['target'])
                if phase == 'training':
                    core.feedback(decision, features, policy, int(correct))
                row = {'phase': phase, 'index': i, 'tile_id': tile['id'], 'policy': policy,
                       'target': tile['target'], 'correct': correct, 'feedback_count': core.feedback_count,
                       'neural': {k: tile['vision'][k] for k in ('spikes', 'active_neurons', 'simulated_ms', 'spike_sha256')}}
                records.append(row)
                emit(row)
                if phase == 'training' and (i+1) % 24 == 0:
                    progress(f'Waiting for training after {i+1} choices')
                    core.settle(features)
        after = core.settle(test[-1]['vision']['features'])
        # Public observables, not a claim to have inspected closed-source weight bytes.
        fields = ('sample_count', 'learner_version', 'model')
        same = all(frozen.get(k) == after.get(k) for k in fields)
        if not same:
            raise RunError('Public policy state changed during the no-feedback test.')
        return {'seed': seed, 'domain_id': core.domain_id, 'metrics': measured_metrics(records),
                'feedback_admitted': core.feedback_count, 'test_feedback': 0, 'train_test_exact_overlap': 0,
                'initial_policy_state': initial, 'policy_state_before_test': frozen, 'policy_state_after_test': after,
                'public_policy_state_unchanged': same,
                'task_start': 'fresh hosted Domain, not a reset of the entire hosted agent',
                'protocol': '18 baseline decisions, 360 training choices, 180 held-out image decisions; feedback during training only.',
                'neural_input': '64 fixed simulated fly features; no image labels, pixels, target or tile ID in query context'}
    finally:
        core.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--output', type=Path, default=Path('runs/latest'))
    args = parser.parse_args()
    tiles = read_tiles()
    key = getpass.getpass('Neuroadapt API key (hidden): ').strip()
    core = HostedCore(key, list(tiles[0]['vision']['features']))
    del key
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'domain.json').write_text(json.dumps(core.spec, indent=2)+'\n')
    rows = []
    try:
        result = run_experiment(core, tiles, args.seed, rows.append, lambda s: print(s, flush=True))
        (args.output / 'results.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result['metrics'], indent=2), flush=True)
    finally:
        (args.output / 'decisions.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (args.output / 'api-trace.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in core.calls))


if __name__ == '__main__':
    main()
