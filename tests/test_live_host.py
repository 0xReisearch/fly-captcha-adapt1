import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import live_app
from production import ProductionController
from hosted import RunStopped


def test_production_controller_contract():
    calls = []
    count = 0
    def handle(request):
        nonlocal count
        body = json.loads(request.content)
        assert request.headers['authorization'] == 'Bearer test-visitor-key-not-real'
        calls.append((request.url.path, body))
        if request.url.path.endswith('/feedback'):
            count += 1
            return httpx.Response(200, json={'credit_assignment': {'contextual_learning_applied': True}})
        if request.url.path.endswith('/query'):
            return httpx.Response(200, json={'selection': {'selected_policy': 'inspect_again'}, 'decision_id': 'decision-1'})
        if request.url.path.endswith('/explain'):
            assert 'return_fields' not in body
            return httpx.Response(200, json={'learning_state': {'subsystems': {'feedback_policy': {
                'sample_count': count, 'learner_version': count, 'model': {'status': 'idle'}}}}})
        return httpx.Response(201, json={'domain_id': body['domain_id']})
    stop = threading.Event()
    core = ProductionController('test-visitor-key-not-real', stop, httpx.MockTransport(handle))
    before = core.fingerprint()
    context = {'margin': .1, 'neural_variation': .2, 'experience': 0}
    inspect, decision = core.decide(context, True)
    core.feedback({'controller': decision, 'context': context, 'inspection': inspect}, 1)
    assert core.feedback_count == 1 and core.settle()['sample_count'] == 1
    assert core.fingerprint() != before
    current = core.fingerprint()
    core.decide(context, False)
    assert core.fingerprint() == current
    assert all('neural_00' not in json.dumps(body) and 'target' not in body for _, body in calls)
    feedback = next(body for path, body in calls if path.endswith('/feedback'))
    assert feedback['values']['reward'] == .98
    assert feedback['decision_id'] == 'decision-1'
    assert 'test-visitor-key-not-real' not in json.dumps(core.calls)
    stop.set()
    with pytest.raises(RunStopped):
        core.decide(context, False)
    core.close()
    assert 'Authorization' not in core.remote.client.headers


def fake_lab(vendor, **options):
    app = FastAPI()
    state = {'running': False, 'status': 'Ready', 'run_id': None}
    app.state.lab = state
    app.state.stop = options['stop_event']
    async def shutdown():
        app.state.stop.set()
        app.state.closed = True
    app.state.shutdown = shutdown
    @app.post('/api/start')
    def start():
        options['controller_factory']()
        state.update(running=True, status='Training', run_id='opaque-run')
        return {'status': 'started'}
    @app.post('/api/stop')
    def stop():
        state.update(running=False, status='Stopped')
        return {'status': 'stopped'}
    @app.get('/api/state')
    def get():
        return dict(state)
    return app


def test_visitor_isolation_key_required_and_cleanup():
    seen = []
    def controller(key, stop):
        seen.append(key)
        return SimpleNamespace()
    app = live_app.create_app(controller, fake_lab)
    with TestClient(app, base_url=live_app.ORIGIN) as first, TestClient(app, base_url=live_app.ORIGIN) as second:
        first.get('/live'); second.get('/live')
        headers = {'Origin': live_app.ORIGIN}
        assert first.post('/api/start', headers=headers, json={}).status_code == 422
        assert first.post('/api/start', headers={'Origin': 'https://evil.example'}, json={}).status_code == 403
        assert first.post('/api/start', headers=headers, content='x'*5000).status_code == 415
        assert first.post('/api/start', headers={**headers, 'Content-Type': 'application/json'}, content='x'*5000).status_code == 413
        secret = 'visitor-one-test-key-not-real'
        assert first.post('/api/start', headers=headers, json={'api_key': secret}).status_code == 200
        assert seen == [secret]
        assert secret not in first.get('/api/state').text
        assert first.get('/api/state').json()['running']
        assert not second.get('/api/state').json()['running']
        assert second.post('/api/stop', headers=headers).status_code == 404
        assert second.get('/api/download/domain.json').status_code == 404
        assert first.post('/api/start', headers=headers, json={'api_key': secret}).status_code == 409
        assert first.post('/api/end', headers=headers).status_code == 409
        assert first.get('/.env').status_code == 404
        assert first.get('/anatomy/unknown').status_code == 404
        assert first.post('/api/stop', headers=headers).status_code == 200
        run = next(iter(app.state.runs.values()))
        path = Path(run['directory'].name)
        assert not run['keys']
        assert first.post('/api/end', headers=headers).status_code == 200
        assert not path.exists() and not app.state.runs and run['lab'].state.closed
        assert 'data-recording-only="true"' in first.get('/').text
        assert first.get('/api/replay').status_code == 200
