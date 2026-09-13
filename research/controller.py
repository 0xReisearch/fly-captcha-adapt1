"""Local Adapt-1 controls inspection budget, never the tile answer."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import uuid


def declaration(identity):
    return {
        'domain_id': identity, 'session_id': identity,
        'description': 'Allocate an optional additional sensory observation from measured utility.',
        'schema': {'event_types': ['inspection_trial'], 'entities': [], 'relations': ['inspection_budget'],
                   'signals': ['margin', 'neural_variation', 'experience', 'reward']},
        'hypotheses': [{'name': p, 'policy': p, 'relation': 'inspection_budget', 'weight': 1}
                       for p in ('answer_now', 'inspect_again')],
        'learning': {
            'enabled': True,
            'context': {'feature_paths': ['values.margin', 'values.neural_variation', 'values.experience'],
                        'event_types': ['inspection_trial'], 'max_samples': 1024},
            'reward': {'components': [{'field': 'values.reward', 'goal': 'maximize', 'min': 0, 'max': 1}]},
            'policy': {'exploration_mode': 'ucb', 'exploration_strength': .7,
                       'min_context_observations': 2, 'minimum_confidence': 0,
                       'abstain_on_ood': False, 'transfer_strength': 0, 'action_transfer_strength': 0},
            'latent_belief': {'enabled': False},
            'training': {'enabled': True, 'min_samples': 24, 'retrain_interval': 24,
                         'dimensions': 64, 'epochs': 20},
        },
    }


class LocalController:
    def __init__(self, core_path):
        sys.path.insert(0, str(Path(core_path).resolve() / 'src'))
        os.environ.setdefault('HF_HUB_OFFLINE', '1')
        from fastapi.testclient import TestClient
        from neuroadapt import NeuroadaptEngine
        from neuroadapt.api import create_app
        from neuroadapt.config import NeuroadaptSettings
        self.identity = 'fly-inspection-' + uuid.uuid4().hex
        self.spec = declaration(self.identity)
        self.client = TestClient(create_app(engine=NeuroadaptEngine(), settings=NeuroadaptSettings(
            database_url=None, gpu_upstream_url=None)))
        self.client.__enter__()
        self.calls = []
        self.feedback_count = 0
        self.path = f'/api/v1/domains/{self.identity}'
        try:
            self.call('/api/v1/domains', self.spec)
        except Exception:
            self.client.__exit__(None, None, None)
            raise

    def call(self, path, body):
        response = self.client.post(path, json=body)
        if response.status_code not in (200, 201):
            raise RuntimeError(f'Local Core HTTP {response.status_code}: {response.text[:500]}')
        result = response.json()
        self.calls.append({'route': path, 'request': body, 'response': result})
        return result

    def decide(self, context, learning):
        body = {'session_id': self.identity, 'question': 'Allocate the next sensory observation.',
                'relation': 'inspection_budget', 'context': {'values': context},
                'selection_mode': 'ucb' if learning else 'exploit', 'allow_exploration': learning,
                'top_k': 1, 'return_fields': ['decision_id', 'selection', 'learning_state']}
        result = self.call(self.path + '/query', body)
        policy = result['selection'].get('selected_policy')
        if policy not in ('answer_now', 'inspect_again', None):
            raise RuntimeError('Controller chose an undeclared inspection policy')
        return policy == 'inspect_again', {'policy': policy, 'decision_id': result['decision_id'],
                                          'selection': result['selection']}

    def feedback(self, trial, reward):
        decision = trial['controller']
        if decision['policy'] is None:
            return
        utility = max(0, reward - .02*int(trial['inspection']))
        body = {'session_id': self.identity, 'decision_id': decision['decision_id'],
                'feedback_kind': 'execution', 'relation': 'inspection_budget', 'policy': decision['policy'],
                'values': {'reward': utility}, 'context': {'values': trial['context']},
                'outcome': 'success' if reward else 'failure'}
        result = self.call(self.path + '/feedback', body)
        if not result.get('credit_assignment', {}).get('contextual_learning_applied'):
            raise RuntimeError('Controller feedback was not admitted')
        self.feedback_count += 1

    def settle(self):
        registry = self.client.app.state.domain_registry
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with registry._policy_training_lock:
                busy = any(not f.done() for f in registry._policy_training_futures.values())
                running = any(l.training_status.get('status') == 'running' for l in registry.contextual_learners.values())
            if not busy and not running:
                return
            time.sleep(.05)
        raise TimeoutError('Local controller training did not settle')

    def fingerprint(self):
        registry = self.client.app.state.domain_registry
        state = {}
        for key, learner in registry.contextual_learners.items():
            exported = learner.export_state()
            state[str(key)] = {field: exported[field] for field in ('samples', 'model', 'version', 'calibration')}
        return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()

    def close(self):
        self.settle()
        self.client.__exit__(None, None, None)
