import copy
import unittest

import numpy as np

from circuit import FlyAgent, RewardCircuit
from controller import declaration


class CircuitTests(unittest.TestCase):
    def test_only_rewarded_action_changes(self):
        circuit = RewardCircuit(4, ['a', 'b'], 1)
        _, z, _ = circuit.choose([.1, .8, .2, .4])
        before = circuit.weights.copy()
        circuit.reinforce(1, z, 1)
        np.testing.assert_array_equal(circuit.weights[0], before[0])
        self.assertGreater(float(circuit.weights[1] @ z), 0)
        self.assertEqual(circuit.updates.tolist(), [0, 1])

    def test_zero_reward_suppresses_selected_action(self):
        agent = FlyAgent(2)
        _, z, _ = agent.decision.choose(np.arange(64)/100)
        trial = {'action': 1, 'eligibility': z, 'attention': None}
        agent.feedback(trial, 0)
        self.assertLess(float(agent.decision.weights[1] @ z), 0)

    def test_frozen_inference_and_independent_agents(self):
        agent = FlyAgent(3)
        other = copy.deepcopy(agent)
        before = agent.fingerprint()
        for _ in range(8):
            agent.decision.choose(np.arange(64)/100)
        self.assertEqual(agent.fingerprint(), before)
        action, z, _ = agent.decision.choose(np.arange(64)/100)
        agent.decision.reinforce(action, z, 1)
        self.assertEqual(other.fingerprint(), before)
        self.assertNotEqual(agent.fingerprint(), before)

    def test_delayed_credit_reaches_attention(self):
        agent = FlyAgent(3)
        _, z, _ = agent.decision.choose(np.arange(64)/100)
        _, a, _ = agent.attention.choose(np.arange(64)/100)
        before = agent.attention.fingerprint()
        agent.feedback({'action': 0, 'eligibility': z, 'attention': (2, a)}, 1)
        self.assertNotEqual(agent.attention.fingerprint(), before)
        self.assertEqual(agent.attention.updates.tolist(), [0, 0, 1])

    def test_controller_cannot_choose_tiles(self):
        spec = declaration('unit')
        self.assertEqual({h['policy'] for h in spec['hypotheses']}, {'answer_now', 'inspect_again'})
        self.assertNotIn('target', str(spec))
        self.assertNotIn('neural_00', str(spec))

    def test_invalid_inputs(self):
        circuit = RewardCircuit(2, ['a'], 1)
        with self.assertRaises(ValueError):
            circuit.choose([0, float('nan')])
        with self.assertRaises(ValueError):
            circuit.choose([0])
        with self.assertRaises(ValueError):
            circuit.reinforce(0, [0], 1)
        with self.assertRaises(ValueError):
            FlyAgent(1, attention_epsilon=2)
        with self.assertRaises(ValueError):
            RewardCircuit(2, ['a'], 1, forgetting=0)

    def test_view_value_can_recover_after_outcome_changes(self):
        circuit = RewardCircuit(4, ['a'], 1, forgetting=.95)
        _, z, _ = circuit.choose([.1, .2, .3, .4])
        for _ in range(80):
            circuit.reinforce(0, z, -1)
        for _ in range(60):
            circuit.reinforce(0, z, 1)
        self.assertGreater(float(circuit.weights[0] @ z), .8)

    def test_learns_from_chosen_action_reward(self):
        circuit = RewardCircuit(4, ['a', 'b'], 4)
        rng = np.random.default_rng(44)
        for _ in range(300):
            x = rng.normal(size=4)
            a, z, _ = circuit.choose(x, learning=True)
            correct = (a == int(x[0] > x[1]))
            circuit.reinforce(a, z, 1 if correct else -1)
        hits = 0
        for _ in range(100):
            x = rng.normal(size=4)
            a, _, _ = circuit.choose(x)
            hits += a == int(x[0] > x[1])
        self.assertGreaterEqual(hits, 85)


if __name__ == '__main__':
    unittest.main()
