"""Artificial reward-plastic readout attached to measured fly activity.

This is not a reconstruction of biological KC/MBON learning. Only the chosen
action's reward is fitted, by recursive least squares over a fixed nonlinear
expansion. The attention circuit receives the final outcome with an inspection
cost, providing delayed credit to its earlier viewing choice.
"""
import hashlib
import numpy as np


class RewardCircuit:
    def __init__(self, inputs, actions, seed, hidden=128, ridge=1.0, forgetting=1.0):
        if not 0 < forgetting <= 1:
            raise ValueError('Forgetting factor must be in (0, 1]')
        self.forgetting = forgetting
        self.actions = tuple(actions)
        self.rng = np.random.default_rng(seed)
        self.projection = self.rng.normal(0, 1/np.sqrt(inputs), (hidden, inputs))
        self.offset = self.rng.uniform(-1, 1, hidden)
        size = inputs + hidden + 1
        self.weights = np.zeros((len(actions), size))
        self.precision = np.repeat((np.eye(size)/ridge)[None], len(actions), axis=0)
        self.updates = np.zeros(len(actions), dtype=int)

    def encode(self, observation):
        x = np.asarray(observation, dtype=float)
        if x.shape != (self.projection.shape[1],) or not np.isfinite(x).all():
            raise ValueError('Invalid neural observation')
        # Per-observation normalization uses neither stored labels nor test statistics.
        x = (x - x.mean()) / max(x.std(), .005)
        return np.r_[x/np.sqrt(len(x)), np.tanh(self.projection @ x + self.offset)/np.sqrt(len(self.offset)), 1.0]

    def choose(self, observation, learning=False, epsilon=.15):
        z = self.encode(observation)
        scores = self.weights @ z
        if learning and self.rng.random() < epsilon:
            action = int(self.rng.integers(len(self.actions)))
        else:
            ties = np.flatnonzero(np.isclose(scores, scores.max(), atol=1e-12, rtol=0))
            # Deterministic tie handling also keeps inference RNG state frozen.
            action = int(ties[0])
        return action, z, scores

    def reinforce(self, action, eligibility, reward):
        if not 0 <= action < len(self.actions) or not np.isfinite(reward) or not -1 <= reward <= 1:
            raise ValueError('Invalid chosen-action reward')
        z = np.asarray(eligibility, dtype=float)
        if z.shape != self.weights[action].shape or not np.isfinite(z).all():
            raise ValueError('Invalid eligibility trace')
        p = self.precision[action]
        projection = p @ z
        gain = projection / (self.forgetting + z @ projection)
        error = reward - float(self.weights[action] @ z)
        self.weights[action] += gain * error
        p -= np.outer(gain, projection)
        self.precision[action] = (p + p.T) * (.5/self.forgetting)
        self.updates[action] += 1
        return error

    def fingerprint(self):
        h = hashlib.sha256()
        for array in (self.projection, self.offset, self.weights, self.precision, self.updates):
            h.update(array.tobytes())
        return h.hexdigest()


class FlyAgent:
    def __init__(self, seed, attention_forgetting=.98, attention_epsilon=.3):
        if not 0 <= attention_epsilon <= 1:
            raise ValueError('Attention exploration must be between zero and one')
        self.attention_epsilon = attention_epsilon
        self.decision = RewardCircuit(64, ('leave', 'select'), seed)
        # View utility changes while the answer readout learns: discount old view
        # outcomes instead of treating the first untrained mistakes as permanent.
        self.attention = RewardCircuit(64, ('left', 'center', 'right'), seed+1000, forgetting=attention_forgetting)
        self.feedback_count = 0

    def fingerprint(self):
        return hashlib.sha256((self.decision.fingerprint() + self.attention.fingerprint()).encode()).hexdigest()

    def act(self, eye, image, permit_inspection, learning=False, erase_signal=False, on_observation=None):
        eye.reset()
        wide, first, counts = eye.observe(image)
        if erase_signal:
            wide = np.zeros_like(wide)
        if on_observation:
            on_observation(first, counts)
        _, _, preliminary = self.decision.choose(wide)
        context = {'margin': float(abs(preliminary[1]-preliminary[0])),
                   'neural_variation': float(wide.std()), 'experience': self.feedback_count}
        inspection, controller_trace = permit_inspection(context)
        views = [first]
        attention = None
        final = wide
        if inspection:
            index, eligibility, scores = self.attention.choose(wide, learning, epsilon=self.attention_epsilon)
            view = self.attention.actions[index]
            close, observation, counts = eye.observe(image, view)
            if erase_signal:
                close = np.zeros_like(close)
            if on_observation:
                on_observation(observation, counts)
            # Preserve the overview; a glimpse adds evidence rather than discarding it.
            final = (wide + close)*.5
            views.append(observation)
            attention = (index, eligibility)
        action, eligibility, scores = self.decision.choose(final, learning)
        return {'policy': self.decision.actions[action], 'action': action, 'eligibility': eligibility,
                'attention': attention, 'views': views, 'scores': scores.tolist(), 'context': context,
                'controller': controller_trace, 'inspection': inspection}

    def feedback(self, trial, reward):
        # The caller computes reward only after act() returned its irrevocable choice.
        error = self.decision.reinforce(trial['action'], trial['eligibility'], 2*reward-1)
        if trial['attention'] is not None:
            action, eligibility = trial['attention']
            self.attention.reinforce(action, eligibility, max(-1, 2*reward-1-.02))
        self.feedback_count += 1
        return error
