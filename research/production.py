"""Production Domain API adapter: inspection decisions only, visitor-owned keys."""
import hashlib
import json
import time

from controller import LocalController, declaration
from hosted import HostedCore, RunError, RunStopped


class ProductionController(LocalController):
    description = 'production Adapt-1 inspection budget'
    verification = 'public sample count, learner version and model metadata; not private weight inspection'

    def __init__(self, key, stop=None, transport=None):
        self.remote = HostedCore(key, [], stop, transport)
        self.identity = self.remote.domain_id
        self.path = f'/api/v1/domains/{self.identity}'
        self.spec = declaration(self.identity)
        self.calls = self.remote.calls
        self.feedback_count = 0
        self.last_context = {'margin': 0, 'neural_variation': 0, 'experience': 0}
        try:
            self.call('/api/v1/domains', self.spec)
            self.settle()
        except Exception:
            self.close()
            raise

    def call(self, path, body):
        if not path.startswith('/api/v1/domains'):
            raise RunError('Unexpected controller API route.')
        return self.remote.call(path.removeprefix('/api/v1/'), body)

    def decide(self, context, learning):
        self.last_context = dict(context)
        return super().decide(context, learning)

    def public_state(self):
        response = self.call(self.path+'/explain', {
            'session_id': self.identity, 'question': 'Inspect the sensory budget learner.',
            'relation': 'inspection_budget', 'context': {'values': self.last_context},
            'selection_mode': 'exploit', 'allow_exploration': False, 'top_k': 1})
        return HostedCore.policy_state(response)

    def settle(self):
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            policy = self.public_state()
            if policy['sample_count'] == self.feedback_count and policy['model'].get('status') not in (
                    'running', 'queued', 'training', 'pending'):
                return policy
            if self.remote.stop.wait(2):
                raise RunStopped('Run stopped. Accepted feedback remains in your Domain.')
        raise RunError('Production policy admission/training did not settle within five minutes.')

    def fingerprint(self):
        state = self.public_state()
        observed = {k: state.get(k) for k in ('sample_count', 'learner_version', 'model')}
        return hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()

    def close(self):
        self.remote.close()
