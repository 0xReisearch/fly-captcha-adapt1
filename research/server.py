"""Loopback-only live neural lab with a configurable inspection controller."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import random
import sys
import threading
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image
from starlette.middleware.trustedhost import TrustedHostMiddleware
import numpy as np
import uvicorn

from run import ROOT, dataset, experiment
from sensory import LiveEye
sys.path.insert(0, str(ROOT))
from hosted import RunError, RunStopped


class PlayRequest(BaseModel):
    board_id: str
    selections: list[int] | None = Field(default=None, max_length=9)


def create_lab(vendor, core=None, port=8794, limit=None, overview_size=2,
               controller_factory=None, output_root=None, seed=17, stop_event=None, safe_errors=False):
    state = {'running': False, 'status': 'Ready', 'record': None, 'observation': None,
             'results': None, 'history': [], 'board': [], 'cursor': 0, 'run_id': None,
             'trained': False, 'mode': 'experiment', 'practice': None, 'practice_rounds': 0,
             'practice_bananas': 0, 'board_choices': {}}
    lock = threading.Lock()
    stop = stop_event or threading.Event()
    worker_thread = None
    retained = {}
    practice_tiles = []

    def release():
        controller = retained.get('controller')
        if controller:
            controller.close()
        retained.clear()

    async def shutdown():
        stop.set()
        if worker_thread is not None:
            await asyncio.to_thread(worker_thread.join, 190)
        if worker_thread is not None and worker_thread.is_alive():
            raise RuntimeError('Worker has not stopped')
        await asyncio.to_thread(release)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await shutdown()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    app.state.lab = state
    app.state.stop = stop
    app.state.shutdown = shutdown

    @app.middleware('http')
    async def local_only(request, call_next):
        if request.method == 'POST' and request.headers.get('origin') not in (
                f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Local same-origin request required'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'research/web/index.html')

    @app.get('/api/state')
    def current():
        with lock:
            return dict(state)

    @app.get('/api/results')
    def results():
        with lock:
            return state['results'] or {'status': state['status']}

    @app.get('/anatomy/positions.f32')
    def positions():
        return FileResponse(ROOT / 'data/anatomy/positions.f32')

    @app.get('/icons.js')
    def icons():
        return FileResponse(ROOT / 'public/icons.js')

    def work(seed):
        prepared = None
        try:
            release()
            if controller_factory:
                with lock:
                    state['status'] = 'Connecting to production Neuroadapt'
                prepared = controller_factory()
            with lock:
                state['status'] = 'Loading live neural simulator'
            eye = LiveEye(vendor, overview_size)
            train, test = dataset()
            rng = random.Random(seed)
            rng.shuffle(train)
            rng.shuffle(test)
            if limit:
                train, test = train[:limit], test[:min(limit, 36)]

            def observation(tile_id, phase, neural, counts):
                tiles = train if phase == 'training' else test
                index = next(i for i, t in enumerate(tiles) if t['id'] == tile_id)
                active = np.flatnonzero(counts)
                payload = {'tile_id': tile_id, 'phase': phase, **neural,
                           'ids': active.tolist(), 'counts': counts[active].tolist()}
                with lock:
                    board = [t['id'] for t in tiles[index//9*9:index//9*9+9]]
                    if state['board'] != board or (state['observation'] or {}).get('phase') != phase:
                        state['board_choices'] = {}
                    state.update(observation=payload, status=phase.replace('_', ' ').title(), overview_size=overview_size,
                                 board=board,
                                 tile_index=index % 9, cursor=state['cursor']+1)
                # Presentation pacing is interruptible and never changes simulation time.
                if stop.wait(.08):
                    raise InterruptedError('Stopped')

            def emit(record):
                with lock:
                    state['record'] = record
                    state['board_choices'][record['tile_id']] = record['policy']
                    state['history'].append({'phase': record['phase'], 'correct': record['correct'],
                                             'inspection': record['inspection']})

            def keep(fly, eye, controller, directory):
                retained.update(fly=fly, eye=eye, controller=controller, directory=directory)

            directory = Path(output_root or ROOT / 'artifacts/live-lab') / (time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
            result = experiment(eye, seed, directory, core, limit, emit, observation, stop,
                                controls=False, retain=keep, controller_factory=(lambda: prepared) if prepared else None)
            with lock:
                state['results'] = result
                state['status'] = 'Complete'
                state['trained'] = True
        except (InterruptedError, RunStopped):
            with lock:
                state['status'] = 'Stopped'
        except Exception as exc:
            with lock:
                state['status'] = 'Failed: '+(str(exc)[:300] if not safe_errors or isinstance(exc, RunError)
                                             else 'Experiment stopped after an internal check. No automatic write retry.')
        finally:
            if prepared and not retained:
                prepared.close()
            with lock:
                state['running'] = False

    @app.post('/api/start')
    def start():
        nonlocal worker_thread
        with lock:
            if state['running']:
                raise HTTPException(409, 'A local experiment is already running')
            stop.clear()
            state.update(running=True, status='Starting', record=None, observation=None,
                         results=None, history=[], cursor=0, board=[], seed=seed, run_id=uuid.uuid4().hex,
                         trained=False, mode='experiment', practice=None, practice_rounds=0,
                         practice_bananas=0, board_choices={})
            worker_thread = threading.Thread(target=work, args=(seed,), daemon=True)
            worker_thread.start()
        return {'status': 'started', 'seed': seed}

    @app.post('/api/practice/board')
    def new_board():
        nonlocal practice_tiles
        with lock:
            if state['running']:
                raise HTTPException(409, 'Wait for the current round to stop')
            if not state['trained']:
                raise HTTPException(409, 'Complete a fresh training run first')
            _, test = dataset()
            practice_tiles = random.SystemRandom().sample(test, 9)
            board_id = uuid.uuid4().hex
            state.update(mode='practice', status='Your move', board=[t['id'] for t in practice_tiles],
                         record=None, observation=None, tile_index=None, board_choices={},
                         practice={'board_id': board_id, 'stage': 'choosing', 'rows': [], 'result': None})
            return {'board_id': board_id}

    def practice_work(tiles, selections, board_id):
        fly, eye, controller = (retained[k] for k in ('fly', 'eye', 'controller'))
        before = fly.fingerprint()
        core_before = None
        rows = []
        started = time.monotonic()
        call_start = len(controller.calls) if controller else 0
        try:
            core_before = controller.fingerprint() if controller else None
            for index, tile in enumerate(tiles):
                if stop.is_set():
                    raise InterruptedError('Stopped')

                def budget(context):
                    if stop.is_set():
                        raise InterruptedError('Stopped')
                    return controller.decide(context, False) if controller else (True, {'policy': 'fixed_inspection'})

                def capture(neural, counts):
                    if stop.is_set():
                        raise InterruptedError('Stopped')
                    active = np.flatnonzero(counts)
                    with lock:
                        state.update(observation={'tile_id': tile['id'], 'phase': 'practice', **neural,
                                                  'ids': active.tolist(), 'counts': counts[active].tolist()},
                                     tile_index=index, cursor=state['cursor']+1)
                    if stop.wait(.45):
                        raise InterruptedError('Stopped')

                with Image.open(ROOT/'data/tiles'/(tile['id']+'.jpg')) as image:
                    trial = fly.act(eye, image, budget, learning=False, on_observation=capture)
                correct = (trial['policy'] == 'select') == tile['target']
                row = {k: v for k, v in trial.items() if k not in ('eligibility', 'attention')}
                row.update(phase='practice', tile_id=tile['id'], correct=correct,
                           feedback_count=fly.feedback_count, reward_prediction_error=None)
                rows.append(row)
                with lock:
                    state['record'] = row
                    state['practice']['rows'] = list(rows)
                if stop.wait(.35):
                    raise InterruptedError('Stopped')
            assert fly.fingerprint() == before, 'Practice changed the fly learner'
            assert controller is None or controller.fingerprint() == core_before, 'Practice changed Core learner'
            eye.verify_fixed_graph()
            score = sum(r['correct'] for r in rows)
            human = None if selections is None else sum((i in selections) == t['target'] for i, t in enumerate(tiles))
            result = {'fly_correct': score, 'human_correct': human, 'tiles': 9,
                      'passed': score == 9, 'elapsed_seconds': time.monotonic()-started,
                      'feedback': 0, 'fly_unchanged': True, 'core_unchanged': True,
                      'target_indices': [i for i, t in enumerate(tiles) if t['target']],
                      'protocol': 'Practice only: resampled existing held-out photos. Excluded from evaluation.'}
            with lock:
                state['practice']['result'] = result
                state['practice']['stage'] = 'complete'
                state['practice_rounds'] += 1
                state['practice_bananas'] += int(score == 9)
        except (InterruptedError, RunStopped):
            with lock:
                state['status'] = 'Stopped'
                state['practice']['stage'] = 'stopped'
        except Exception as exc:
            with lock:
                state['status'] = 'Failed: '+(str(exc)[:300] if not safe_errors or isinstance(exc, RunError)
                                             else 'Practice stopped after an internal check.')
                state['practice']['stage'] = 'failed'
        finally:
            audit = {'board_id': board_id, 'rows': rows, 'human_selections': selections,
                     'result': state['practice']['result'], 'fly_unchanged': fly.fingerprint() == before,
                     'core_calls': controller.calls[call_start:] if controller else []}
            try:
                with (retained['directory']/'practice.jsonl').open('a') as stream:
                    stream.write(json.dumps(audit)+'\n')
            except OSError:
                with lock:
                    state['status'] = 'Failed: practice trace could not be retained.'
                    state['practice']['stage'] = 'failed'
            finally:
                with lock:
                    state['running'] = False
                    if state['practice']['stage'] == 'complete':
                        state['status'] = 'Round complete'

    @app.post('/api/practice/play')
    def play(body: PlayRequest):
        nonlocal worker_thread
        if body.selections is not None and (len(set(body.selections)) != len(body.selections)
                                            or any(i < 0 or i > 8 for i in body.selections)):
            raise HTTPException(422, 'Selections must be unique tile indices from 0 to 8')
        with lock:
            if state['running']:
                raise HTTPException(409, 'A round is already running')
            practice = state['practice']
            if not state['trained'] or not practice or practice['board_id'] != body.board_id or practice['stage'] != 'choosing':
                raise HTTPException(409, 'Request a new practice board first')
            stop.clear()
            practice['stage'] = 'playing'
            state.update(running=True, status='Fly taking the test')
            worker_thread = threading.Thread(target=practice_work,
                                             args=(list(practice_tiles), body.selections, body.board_id), daemon=True)
            worker_thread.start()
        return {'status': 'started'}

    @app.post('/api/stop')
    def halt():
        stop.set()
        with lock:
            if state['running']:
                state['status'] = 'Stopping'
        return {'status': 'stopping'}

    for route, folder in (('/static', 'research/web'), ('/tiles', 'data/tiles'),
                          ('/fruitless', 'public/fruitless'), ('/three', 'public/three'),
                          ('/fonts', 'public/fonts')):
        app.mount(route, StaticFiles(directory=ROOT/folder), name=route[1:])
    return app


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--vendor', required=True)
    parser.add_argument('--core', required=True)
    parser.add_argument('--port', type=int, default=8794)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--overview-size', type=int, default=2)
    args = parser.parse_args()
    uvicorn.run(create_lab(args.vendor, args.core, args.port, args.limit, args.overview_size), host='127.0.0.1',
                port=args.port, access_log=False)
