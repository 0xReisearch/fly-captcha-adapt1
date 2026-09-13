"""CPU-only web host. Credentials and visitor runs are retained in RAM only."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from hosted import HostedCore, RunError, RunStopped, read_tiles, run_experiment

ROOT = Path(__file__).resolve().parent
ORIGIN = os.environ.get('PUBLIC_ORIGIN', 'http://127.0.0.1:8793').rstrip('/')
COOKIE = '__Host-fly-visitor' if ORIGIN.startswith('https://') else 'fly-visitor-local'
TTL = 7200
MAX_RUNNING = 3
MAX_RETAINED = 12


def create_app(core_factory=HostedCore):
    runs = {}
    tiles = read_tiles()
    reference = json.loads((ROOT / 'data/reference.json').read_text())

    def cleanup():
        for run_id, run in list(runs.items()):
            if time.monotonic() - run['created'] > TTL:
                run['stop'].set()
                if not run['running']:
                    del runs[run_id]

    @asynccontextmanager
    async def lifespan(app):
        async def reap():
            while True:
                await asyncio.sleep(30)
                cleanup()
        task = asyncio.create_task(reap())
        yield
        task.cancel()
        for run in runs.values():
            run['stop'].set()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    from urllib.parse import urlsplit
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(ORIGIN).hostname, 'localhost', '127.0.0.1', 'testserver'])
    app.state.runs = runs

    @app.middleware('http')
    async def secure(request, call_next):
        if request.method not in ('GET', 'HEAD', 'POST'):
            response = JSONResponse({'detail': 'Method unavailable.'}, status_code=405)
        elif request.method == 'POST' and request.headers.get('origin') != ORIGIN:
            response = JSONResponse({'detail': 'Same-origin requests required.'}, status_code=403)
        else:
            response = await call_next(request)
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
            'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        })
        if ORIGIN.startswith('https://'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.api_route('/', methods=['GET', 'HEAD'])
    async def index(request: Request):
        response = FileResponse(ROOT / 'web/index.html')
        if not request.cookies.get(COOKIE):
            response.set_cookie(COOKIE, secrets.token_urlsafe(32), max_age=TTL,
                                secure=ORIGIN.startswith('https://'), httponly=True, samesite='strict')
        return response

    @app.api_route('/healthz', methods=['GET', 'HEAD'])
    async def health():
        return {'status': 'ok'}

    @app.get('/api/replay')
    async def replay():
        return reference

    @app.get('/api/evidence')
    async def evidence():
        return JSONResponse(reference['results'], headers={'Content-Disposition': 'attachment; filename="fly-reference-results.json"'})

    @app.get('/api/trace')
    async def trace():
        return ndjson(reference['trials'], 'reference-decisions.jsonl')

    @app.get('/api/method')
    async def method():
        return FileResponse(ROOT / 'README.md', media_type='text/plain')

    @app.get('/api/neural-activity')
    async def neural():
        return FileResponse(ROOT / 'data/anatomy/activity.json.gz', media_type='application/json', headers={'Content-Encoding': 'gzip'})

    @app.get('/anatomy/{name}')
    async def anatomy(name: str):
        if name not in ('manifest.json', 'positions.f32'):
            raise HTTPException(404)
        return FileResponse(ROOT / 'data/anatomy' / name)

    @app.get('/icons.js')
    async def icons():
        return FileResponse(ROOT / 'public/icons.js', media_type='text/javascript')

    async def small_json(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'JSON required.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise HTTPException(413, 'Request too large.')
        try:
            value = json.loads(raw)
        except ValueError:
            raise HTTPException(422, 'Invalid JSON.') from None
        if not isinstance(value, dict):
            raise HTTPException(422, 'JSON object required.')
        return value

    def own_run(request):
        cleanup()
        run = runs.get(request.query_params.get('run_id', ''))
        if not run or not secrets.compare_digest(run['owner'], request.cookies.get(COOKIE, '')):
            raise HTTPException(404, 'Run not found or expired. Only the originating browser can access it.')
        return run

    def worker(run, core):
        def emit(row):
            run['events'].append(row)
        def progress(value):
            run['progress'] = value
        try:
            run['result'] = run_experiment(core, tiles, run['seed'], emit, progress)
        except RunStopped:
            run['stopped'] = True
            run['progress'] = 'Stopped. No further learning requests will be sent.'
        except RunError as exc:
            run['error'] = str(exc)
        except Exception:
            # Raw exceptions may carry transport context. Never expose/log them.
            run['error'] = 'Run failed an internal contract check. Download its partial trace.'
        finally:
            core.close()
            run['calls'] = core.calls
            run['running'] = False

    @app.post('/api/start')
    async def start(request: Request):
        cleanup()
        owner = request.cookies.get(COOKIE)
        if not owner or len(owner) > 128:
            raise HTTPException(403, 'Open the demo page first.')
        body = await small_json(request)
        key = body.pop('api_key', None)
        if body or not isinstance(key, str) or not 20 <= len(key) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise HTTPException(422, 'Provide an API key only.')
        if any(r['owner'] == owner and r['running'] for r in runs.values()):
            raise HTTPException(409, 'Your learner is already running.')
        if any(r['owner'] == owner and time.monotonic() - r['created'] < 60 for r in runs.values()):
            raise HTTPException(429, 'Wait one minute between starts.')
        if sum(r['running'] for r in runs.values()) >= MAX_RUNNING or len(runs) >= MAX_RETAINED:
            raise HTTPException(429, 'Demo capacity reached. Try later.')
        run_id = secrets.token_urlsafe(24)
        run = {'owner': owner, 'created': time.monotonic(), 'running': True, 'events': [], 'calls': [],
               'error': None, 'result': None, 'stopped': False, 'progress': 'Connecting to Neuroadapt',
               'seed': secrets.randbelow(1000000), 'stop': threading.Event()}
        core = core_factory(key, list(tiles[0]['vision']['features']), run['stop'])
        del key
        run['domain_id'] = core.domain_id
        runs[run_id] = run
        threading.Thread(target=worker, args=(run, core), daemon=True).start()
        return {'run_id': run_id, 'seed': run['seed'], 'domain_id': core.domain_id, 'status': 'started'}

    @app.post('/api/stop')
    async def stop(request: Request):
        run = own_run(request)
        if not run['running']:
            return {'status': 'stopped' if run['stopped'] else 'finished'}
        run['stop'].set()
        run['progress'] = 'Stopping after the current API request.'
        return {'status': 'stopping'}

    @app.get('/api/current')
    async def current(request: Request):
        cleanup()
        owner = request.cookies.get(COOKIE, '')
        matches = [(run_id, r) for run_id, r in runs.items() if secrets.compare_digest(r['owner'], owner)]
        if not matches:
            return {'run': None}
        run_id, run = max(matches, key=lambda pair: pair[1]['created'])
        return {'run': {'run_id': run_id, 'seed': run['seed'], 'domain_id': run['domain_id'], 'running': run['running']}}

    @app.get('/api/live')
    async def live(request: Request):
        run = own_run(request)
        try:
            cursor = int(request.query_params.get('cursor', '0'))
            if not 0 <= cursor <= 1000:
                raise ValueError()
        except ValueError:
            raise HTTPException(422, 'Invalid cursor.') from None
        end = len(run['events'])
        return {'running': run['running'], 'events': run['events'][cursor:end], 'cursor': end,
                'seed': run['seed'], 'error': run['error'], 'progress': run['progress'], 'domain_id': run['domain_id'],
                'stopping': run['stop'].is_set() and run['running'], 'stopped': run['stopped']}

    @app.get('/api/live/evidence')
    async def live_evidence(request: Request):
        run = own_run(request)
        if run['running']:
            raise HTTPException(409, 'Run is still in progress.')
        result = run['result'] or {'status': 'stopped' if run['stopped'] else 'incomplete', 'error': run['error'], 'domain_id': run['domain_id'], 'completed_choices': len(run['events'])}
        return JSONResponse(result, headers={'Content-Disposition': 'attachment; filename="fly-hosted-results.json"'})

    @app.get('/api/live/trace')
    async def live_trace(request: Request):
        run = own_run(request)
        if run['running']:
            raise HTTPException(409, 'Run is still in progress.')
        return ndjson(run['events'], 'hosted-decisions.jsonl')

    @app.get('/api/live/audit')
    async def audit(request: Request):
        run = own_run(request)
        if run['running']:
            raise HTTPException(409, 'Run is still in progress.')
        return ndjson(run['calls'], 'hosted-api-trace.jsonl')

    for route, directory in [('static', 'web'), ('tiles', 'data/tiles'), ('fruitless', 'public/fruitless'),
                             ('three', 'public/three'), ('fonts', 'public/fonts'), ('licenses', 'licenses')]:
        app.mount('/' + route, StaticFiles(directory=ROOT / directory), name=route)
    return app


def ndjson(rows, name):
    return PlainTextResponse(''.join(json.dumps(row) + '\n' for row in rows), media_type='application/x-ndjson',
                             headers={'Content-Disposition': f'attachment; filename="{name}"'})


app = create_app()
