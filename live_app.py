"""Visitor-isolated live CPU fly sessions, with BYOK production inspection learning."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'research'))
from production import ProductionController
from server import create_lab

ORIGIN = os.environ.get('PUBLIC_ORIGIN', 'http://127.0.0.1:8795').rstrip('/')
COOKIE = '__Host-fly-visitor' if ORIGIN.startswith('https://') else 'fly-visitor-local'
TTL = 7200
MAX_RUNNING = 2
MAX_RETAINED = 3


def create_app(controller_type=ProductionController, lab_factory=create_lab, limit=None):
    runs = {}
    starts = {}
    gate = asyncio.Lock()
    reference = json.loads((ROOT/'data/reference.json').read_text())

    async def dispose(owner):
        run = runs[owner]
        await run['lab'].state.shutdown()
        run['keys'].clear()
        run['directory'].cleanup()
        del runs[owner]

    async def cleanup():
        for owner, run in list(runs.items()):
            if time.monotonic()-run['created'] > TTL:
                run['lab'].state.stop.set()
                if not run['lab'].state.lab['running']:
                    await dispose(owner)
        for owner, created in list(starts.items()):
            if time.monotonic()-created > 60:
                del starts[owner]

    @asynccontextmanager
    async def lifespan(app):
        async def reap():
            while True:
                await asyncio.sleep(15)
                async with gate:
                    await cleanup()
        task = asyncio.create_task(reap())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for run in runs.values():
            run['lab'].state.stop.set()
        for owner in list(runs):
            await dispose(owner)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
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

    @app.api_route('/live', methods=['GET', 'HEAD'])
    async def index(request: Request):
        response = FileResponse(ROOT/'research/web/index.html')
        if not request.cookies.get(COOKIE):
            response.set_cookie(COOKIE, secrets.token_urlsafe(32), max_age=TTL,
                                secure=ORIGIN.startswith('https://'), httponly=True, samesite='strict')
        return response

    @app.api_route('/healthz', methods=['GET', 'HEAD'])
    async def health():
        return {'status': 'ok', 'engine': 'live-fly-production-controller',
                'active': sum(r['lab'].state.lab['running'] for r in runs.values()), 'retained': len(runs)}

    @app.api_route('/', methods=['GET', 'HEAD'])
    @app.get('/recording')
    async def recording():
        html = (ROOT/'web/index.html').read_text().replace('/static/', '/legacy-static/')
        return HTMLResponse(html.replace('<body>', '<body data-recording-only="true">'))

    @app.get('/api/replay')
    async def replay():
        return reference

    @app.get('/api/current')
    async def legacy_current():
        return {'run': None}

    @app.get('/api/evidence')
    async def reference_results():
        return reference['results']

    @app.get('/api/trace')
    async def reference_trace():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(''.join(json.dumps(r)+'\n' for r in reference['trials']),
                                 media_type='application/x-ndjson')

    @app.get('/api/method')
    async def method():
        return FileResponse(ROOT/'README.md', media_type='text/plain')

    @app.get('/api/neural-activity')
    async def reference_neural():
        return FileResponse(ROOT/'data/anatomy/activity.json.gz', media_type='application/json',
                            headers={'Content-Encoding': 'gzip'})

    @app.get('/anatomy/{name}')
    async def anatomy(name: str):
        if name not in ('manifest.json', 'positions.f32'):
            raise HTTPException(404)
        return FileResponse(ROOT/'data/anatomy'/name)

    @app.get('/icons.js')
    async def icons():
        return FileResponse(ROOT/'public/icons.js')

    async def small_json(request):
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, 'JSON required.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise HTTPException(413, 'Request too large.')
        try:
            body = json.loads(raw)
        except ValueError:
            raise HTTPException(422, 'Invalid JSON.') from None
        if not isinstance(body, dict):
            raise HTTPException(422, 'JSON object required.')
        return body

    def owned(request, required=True):
        owner = request.cookies.get(COOKIE, '')
        run = runs.get(owner)
        if run and time.monotonic()-run['created'] > TTL:
            run['lab'].state.stop.set()
            run = None
        if not run and required:
            raise HTTPException(404, 'No active browser session. Start with your own API key.')
        return run

    async def forward(run, path, body=None, method='GET'):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=run['lab']), base_url='http://127.0.0.1:8794') as client:
            response = await client.request(method, path, json=body, headers={'Origin': 'http://127.0.0.1:8794'})
        data = response.json()
        return JSONResponse(data, status_code=response.status_code)

    @app.post('/api/start')
    async def start(request: Request):
        body = await small_json(request)
        key = body.pop('api_key', None)
        if body or not isinstance(key, str) or not 20 <= len(key) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise HTTPException(422, 'Provide your API key only.')
        owner = request.cookies.get(COOKIE, '')
        if not 20 <= len(owner) <= 128:
            raise HTTPException(403, 'Open the demo page first.')
        async with gate:
            await cleanup()
            if owner in runs and runs[owner]['lab'].state.lab['running']:
                raise HTTPException(409, 'Your experiment is already running.')
            if owner in starts:
                raise HTTPException(429, 'Wait one minute between starts.')
            if sum(r['lab'].state.lab['running'] for r in runs.values()) >= MAX_RUNNING:
                raise HTTPException(429, 'Both live CPU slots are busy. The recording is available.')
            if owner not in runs and len(runs) >= MAX_RETAINED:
                raise HTTPException(429, 'Demo capacity reached. Try later or watch the recording.')
            if owner in runs:
                await dispose(owner)
            directory = tempfile.TemporaryDirectory(prefix='fly-session-')
            keys = [key]
            del key
            stop = threading.Event()
            def controller_factory():
                return controller_type(keys.pop(), stop)
            lab = lab_factory(os.environ.get('FLY_VENDOR', str(ROOT/'vendor/doomfly')),
                              controller_factory=controller_factory, output_root=directory.name,
                              seed=secrets.randbelow(1000000), stop_event=stop, limit=limit, safe_errors=True)
            run = {'created': time.monotonic(), 'lab': lab, 'directory': directory, 'keys': keys}
            runs[owner] = run
            starts[owner] = run['created']
            return await forward(run, '/api/start', method='POST')

    @app.get('/api/state')
    async def state(request: Request):
        run = owned(request, required=False)
        if not run:
            return {'hosted': True, 'running': False, 'status': 'Your key. Your fly.', 'record': None,
                    'observation': None, 'results': None, 'history': [], 'board': [], 'cursor': 0,
                    'run_id': None, 'trained': False, 'mode': 'experiment', 'practice': None}
        response = await forward(run, '/api/state')
        data = json.loads(response.body)
        data['hosted'] = True
        data['expires_in_seconds'] = max(0, int(TTL-(time.monotonic()-run['created'])))
        return data

    @app.post('/api/stop')
    async def stop(request: Request):
        return await forward(owned(request), '/api/stop', method='POST')

    @app.post('/api/end')
    async def end(request: Request):
        run = owned(request)
        if run['lab'].state.lab['running']:
            raise HTTPException(409, 'Stop the run before forgetting this session.')
        async with gate:
            await dispose(request.cookies[COOKIE])
        return {'status': 'forgotten'}

    @app.post('/api/practice/board')
    async def board(request: Request):
        return await forward(owned(request), '/api/practice/board', method='POST')

    @app.post('/api/practice/play')
    async def play(request: Request):
        body = await small_json(request)
        async with gate:
            if sum(r['lab'].state.lab['running'] for r in runs.values()) >= MAX_RUNNING:
                raise HTTPException(429, 'Both live CPU slots are busy. Try again shortly.')
            return await forward(owned(request), '/api/practice/play', body, method='POST')

    @app.get('/api/results')
    async def results(request: Request):
        return await forward(owned(request), '/api/results')

    @app.get('/api/download/{name}')
    async def download(name: str, request: Request):
        run = owned(request)
        if run['lab'].state.lab['running']:
            raise HTTPException(409, 'Stop or finish before downloading.')
        if name not in ('results.json', 'trace.jsonl', 'core-api-trace.jsonl', 'domain.json', 'configuration.json', 'practice.jsonl'):
            raise HTTPException(404)
        paths = list(Path(run['directory'].name).glob('*/'+name))
        if len(paths) != 1:
            raise HTTPException(404, 'This artifact is not available for this run.')
        return FileResponse(paths[0], filename=name)

    for route, directory in [('static', 'research/web'), ('legacy-static', 'web'), ('tiles', 'data/tiles'),
                             ('fruitless', 'public/fruitless'), ('three', 'public/three'), ('fonts', 'public/fonts'),
                             ('licenses', 'licenses')]:
        app.mount('/'+route, StaticFiles(directory=ROOT/directory), name=route)
    return app


app = create_app()
