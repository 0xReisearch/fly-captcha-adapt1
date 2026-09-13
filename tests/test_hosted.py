import json
import threading
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from hosted import HostedCore, RunError, RunStopped, declaration, read_tiles
from app import create_app, ORIGIN

KEY = 'test-only-nonfunctional-credential'


class HostedTests(unittest.TestCase):
    def test_stop_blocks_feedback_after_inflight_query(self):
        entered, release = threading.Event(), threading.Event()
        sent = []
        clients = []
        def handler(request):
            sent.append(request.url.path)
            self.assertEqual(request.headers['authorization'], 'Bearer ' + KEY)
            entered.set()
            release.wait(3)
            return httpx.Response(200, json={'selection': {'selected_policy': 'select'}, 'decision_id': 'd1'})
        def factory(key, features, stop):
            core = HostedCore(key, features, stop, transport=httpx.MockTransport(handler))
            clients.append(core)
            return core
        def experiment(core, tiles, seed, emit, progress):
            policy, decision = core.query({'neural_00': 0.2})
            core.feedback(decision, {'neural_00': 0.2}, policy, 1)
            self.fail('Feedback must not execute after cancellation')
        with patch('app.run_experiment', side_effect=experiment), TestClient(create_app(factory)) as client:
            client.get('/')
            headers = {'origin': ORIGIN}
            started = client.post('/api/start', headers=headers, json={'api_key': KEY}).json()
            run = '?run_id=' + started['run_id']
            self.assertTrue(entered.wait(2))
            self.assertEqual(client.post('/api/stop'+run, headers=headers).json()['status'], 'stopping')
            self.assertTrue(client.get('/api/live'+run).json()['stopping'])
            release.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and client.get('/api/live'+run).json()['running']:
                time.sleep(.01)
            state = client.get('/api/live'+run).json()
            self.assertFalse(state['running'])
            self.assertTrue(state['stopped'])
            self.assertIsNone(state['error'])
            self.assertEqual(client.get('/api/live/evidence'+run).json()['status'], 'stopped')
            self.assertEqual(len(sent), 1)
            self.assertNotIn('Authorization', clients[0].client.headers)
            self.assertEqual(clients[0].feedback_count, 0)

    def test_each_client_uses_its_own_key(self):
        keys = [KEY + '-alice', KEY + '-bob']
        sent = []
        for key in keys:
            def handler(request):
                sent.append(request.headers['authorization'])
                return httpx.Response(201, json={})
            core = HostedCore(key, [], transport=httpx.MockTransport(handler))
            core.create()
            core.close()
        self.assertEqual(sent, ['Bearer '+key for key in keys])

    def test_data_contract(self):
        tiles = read_tiles()
        self.assertEqual(len(tiles), 540)
        spec = declaration('test', list(tiles[0]['vision']['features']))
        self.assertEqual(len(spec['learning']['context']['feature_paths']), 64)
        self.assertNotIn('banana', json.dumps(spec).lower())

    def test_feedback_admission_and_safe_audit(self):
        def handler(request):
            self.assertEqual(request.headers['authorization'], 'Bearer ' + KEY)
            return httpx.Response(201, json={'credit_assignment': {'contextual_learning_applied': True}})
        core = HostedCore(KEY, ['neural_00'], transport=httpx.MockTransport(handler))
        core.feedback({'decision_id': 'decision'}, {'neural_00': 0.1}, 'select', 1)
        self.assertEqual(core.feedback_count, 1)
        self.assertNotIn(KEY, json.dumps(core.calls))
        core.close()
        self.assertNotIn('Authorization', core.client.headers)

    def test_accepted_but_not_learned_fails(self):
        core = HostedCore(KEY, [], transport=httpx.MockTransport(lambda req: httpx.Response(201, json={})))
        with self.assertRaises(RunError):
            core.feedback({'decision_id': 'x'}, {}, 'select', 1)
        self.assertEqual(core.feedback_count, 0)
        core.close()

    def test_explain_contract(self):
        def handler(request):
            self.assertNotIn('return_fields', json.loads(request.content))
            return httpx.Response(200, json={'learning_state': {'subsystems': {'feedback_policy': {
                'sample_count': 0, 'learner_version': 0, 'model': {'status': 'idle'}}}}})
        core = HostedCore(KEY, [], transport=httpx.MockTransport(handler))
        self.assertEqual(core.settle({})['sample_count'], 0)
        core.close()

    def test_ambiguous_write_not_retried(self):
        attempts = []
        def handler(request):
            attempts.append(1)
            return httpx.Response(503, text=KEY)
        core = HostedCore(KEY, [], transport=httpx.MockTransport(handler))
        with self.assertRaises(RunError) as error:
            core.create()
        self.assertNotIn(KEY, str(error.exception))
        self.assertNotIn(KEY, json.dumps(core.calls))
        self.assertEqual(len(attempts), 1)
        core.close()

    def test_visitor_boundaries_and_csrf(self):
        ready = threading.Event()
        def experiment(core, tiles, seed, emit, progress):
            ready.set()
            core.stop.wait(5)
            return {'done': True}
        app = create_app()
        with patch('app.run_experiment', side_effect=experiment), TestClient(app) as a, TestClient(app) as b:
            self.assertEqual(a.get('/api/replay').status_code, 200)
            self.assertEqual(a.get('/.env').status_code, 404)
            self.assertEqual(a.get('/hosted.py').status_code, 404)
            a.get('/')
            b.get('/')
            self.assertEqual(a.post('/api/start', json={'api_key': KEY}).status_code, 403)
            headers = {'origin': ORIGIN}
            self.assertEqual(a.post('/api/start', headers=headers, json={'api_key': KEY, 'url': 'http://localhost'}).status_code, 422)
            response = a.post('/api/start', headers=headers, json={'api_key': KEY})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(ready.wait(2))
            run = '?run_id=' + response.json()['run_id']
            self.assertEqual(b.get('/api/current').json(), {'run': None})
            self.assertEqual(a.get('/api/current').json()['run']['run_id'], response.json()['run_id'])
            self.assertEqual(b.get('/api/live'+run).status_code, 404)
            self.assertEqual(b.post('/api/stop'+run, headers=headers).status_code, 404)
            self.assertEqual(a.get('/api/live'+run).status_code, 200)
            self.assertEqual(a.get('/api/live/audit'+run).status_code, 409)
            self.assertEqual(a.post('/api/start', headers=headers, json={'api_key': KEY}).status_code, 409)
            self.assertEqual(a.post('/api/stop'+run, headers=headers).status_code, 200)
            self.assertNotIn(KEY, a.get('/api/live'+run).text)

    def test_request_size_and_validation_do_not_echo_key(self):
        with TestClient(create_app()) as client:
            client.get('/')
            self.assertEqual(client.post('/api/start', headers={'origin': ORIGIN}, json={}).status_code, 422)
            response = client.post('/api/start', headers={'origin': ORIGIN}, json={'api_key': KEY, 'extra': KEY})
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(KEY, response.text)
            response = client.post('/api/start', headers={'origin': ORIGIN}, json={'api_key': 'x'*5000})
            self.assertEqual(response.status_code, 413)


if __name__ == '__main__':
    unittest.main()
