import asyncio
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import numpy as np
from PIL import Image
from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parents[1] / 'artifacts/live-lab-browser'


async def check(base):
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        errors = []
        page = await browser.new_page(viewport={'width': 1440, 'height': 1100})
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(base)
        await page.wait_for_function("() => document.querySelector('#scene').dataset.ready === 'true'")
        await page.locator('#start').click()
        await page.wait_for_function("() => Number(document.querySelector('#feedback').textContent) >= 3", timeout=180000)
        await page.wait_for_function("() => Number(document.querySelector('#scene').dataset.activeNeurons) > 100")
        first = await page.locator('#scene').get_attribute('data-fly-position')
        pixels = await page.locator('#scene').screenshot()
        assert np.asarray(Image.open(io.BytesIO(pixels))).std() > 15
        await page.screenshot(path=str(OUT/'desktop.png'), full_page=True)
        await page.wait_for_timeout(1500)
        second = await page.locator('#scene').get_attribute('data-fly-position')
        assert first != second
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(1200)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.screenshot(path=str(OUT/'mobile.png'), full_page=True)
        await page.locator('#stop').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Stopped'", timeout=190000)
        a = await (await page.request.get(base+'/api/state')).json()
        await page.wait_for_timeout(1500)
        b = await (await page.request.get(base+'/api/state')).json()
        assert len(a['history']) == len(b['history']) and a['cursor'] == b['cursor']
        assert (await page.request.post(base+'/api/start', headers={'Origin': 'https://example.com'})).status == 403
        assert (await page.request.get(base+'/.env')).status == 404
        await page.reload()
        await page.wait_for_function("() => document.querySelector('#scene').dataset.ready === 'true'")
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Stopped / no experiment running'")
        parked = await page.locator('#scene').get_attribute('data-fly-position')
        await page.wait_for_timeout(1200)
        assert parked == await page.locator('#scene').get_attribute('data-fly-position')
        assert not await page.locator('#scene').get_attribute('data-spike-hash')
        assert json.loads(parked) == [-4, .04, -2]
        # A new start must discard stopped display state and genuinely resume work.
        await page.locator('#start').click()
        await page.wait_for_function("() => document.querySelector('#scene').dataset.runState === 'running'")
        await page.wait_for_function("() => Number(document.querySelector('#scene').dataset.activeNeurons) > 100", timeout=90000)
        await page.wait_for_timeout(1000)
        c = await (await page.request.get(base+'/api/state')).json()
        await page.wait_for_timeout(1800)
        d = await (await page.request.get(base+'/api/state')).json()
        assert c['run_id'] != b['run_id'] and d['cursor'] > c['cursor']
        await page.locator('#stop').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Stopped'", timeout=190000)
        # Finish a short real run, then keep playing with the frozen learners.
        await page.set_viewport_size({'width': 1440, 'height': 1100})
        await page.locator('#start').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Complete'", timeout=190000)
        initial = await (await page.request.get(base+'/api/state')).json()
        assert initial['trained'] and initial['results']['test_feedback'] == 0
        await page.locator('#next').click()
        await page.wait_for_function("() => !document.querySelector('#race').hidden")
        await page.wait_for_function("() => document.querySelector('#scene').dataset.loadedImages === '9'")
        chosen = await (await page.request.get(base+'/api/state')).json()
        assert chosen['practice']['result'] is None
        assert 'target_indices' not in json.dumps(chosen['practice'])
        headers = {'Origin': base}
        assert (await page.request.post(base+'/api/practice/play', headers=headers,
                                       data={'board_id': chosen['practice']['board_id'], 'selections': [9]})).status == 422
        assert (await page.request.post(base+'/api/practice/play', headers=headers,
                                       data={'board_id': 'stale', 'selections': []})).status == 409
        # Project a real tile through the default camera, and click the 3D floor.
        tile = await page.evaluate('''async () => {
            const T = await import('/three/build/three.module.js');
            const r = document.querySelector('#scene').getBoundingClientRect();
            const w = Math.floor(r.width * .7);
            const c = new T.PerspectiveCamera(38, w/r.height, .01, 100);
            c.position.set(3,13,9); c.lookAt(0,0,0); c.updateMatrixWorld();
            const p = new T.Vector3(-2,.02,-1.6).project(c);
            return {x:r.left+(p.x+1)*w/2,y:r.top+(1-p.y)*r.height/2};
        }''')
        await page.mouse.click(tile['x'], tile['y'])
        await page.wait_for_function("() => document.querySelector('#race-label').textContent.includes('(1)')")
        await page.screenshot(path=str(OUT/'challenge-desktop.png'), full_page=True)
        await page.locator('#race').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Round complete'", timeout=90000)
        played = await (await page.request.get(base+'/api/state')).json()
        result = played['practice']['result']
        assert result['fly_unchanged'] and result['core_unchanged'] and result['feedback'] == 0
        assert result['human_correct'] is not None and len(played['practice']['rows']) == 9
        assert played['history'] == initial['history'] and played['results'] == initial['results']
        assert played['record']['feedback_count'] == initial['record']['feedback_count']
        await page.locator('#verdict').wait_for(state='visible', timeout=10000)
        await page.screenshot(path=str(OUT/'verdict-desktop.png'), full_page=True)
        await page.reload()
        await page.wait_for_function("() => document.querySelector('#scene').dataset.ready === 'true'")
        await page.wait_for_function("() => !document.querySelector('#next').disabled")
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.screenshot(path=str(OUT/'verdict-mobile.png'), full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.locator('#next').click()
        await page.wait_for_function("() => !document.querySelector('#watch').hidden")
        await page.locator('#watch').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Fly taking the test'")
        await page.locator('#stop').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Stopped'", timeout=90000)
        stopped = await (await page.request.get(base+'/api/state')).json()
        assert stopped['trained'] and stopped['practice']['stage'] == 'stopped'
        await page.locator('#next').click()
        await page.wait_for_function("() => !document.querySelector('#watch').hidden")
        await page.locator('#watch').click()
        await page.wait_for_function("() => document.querySelector('#status').textContent === 'Round complete'", timeout=90000)
        solo = await (await page.request.get(base+'/api/state')).json()
        assert solo['practice']['result']['human_correct'] is None
        assert solo['practice']['result']['fly_unchanged'] and solo['practice']['result']['core_unchanged']
        assert solo['practice_rounds'] == 2
        assert not errors, errors
        result = {'desktop_nonblank': True, 'mobile_no_overflow': True, 'fly_moves': True,
                  'actual_neuron_activity': True, 'stop_blocks_new_trials': True,
                  'cross_origin_start_rejected': True, 'javascript_errors': errors,
                  'stopped_reload_stays_parked': True, 'fresh_restart_progresses': True,
                  'isolated_test_server': True,
                  'post_training_race': result, 'practice_does_not_change_evaluation': True,
                  'three_dimensional_tile_selection': True, 'solo_round': True,
                  'practice_stop_retains_learner': True, 'completed_reload_playable': True,
                  'feedbacks_before_stop': b['record']['feedback_count']}
        (OUT/'checks.json').write_text(json.dumps(result, indent=2)+'\n')
        print(json.dumps(result), flush=True)
        await browser.close()


async def main():
    import httpx
    root = Path(__file__).resolve().parents[1]
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, CUDA_VISIBLE_DEVICES='', HIP_VISIBLE_DEVICES='', HF_HUB_OFFLINE='1',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    with (OUT/'isolated-server.log').open('w') as log:
        process = subprocess.Popen([sys.executable, str(root/'research/server.py'),
                                    '--vendor', str(root.parent/'fly-human/vendor/doomfly'),
                                    '--core', str(root.parent/'neuroadapt-trajectory-api'), '--port', str(port),
                                    '--limit', '36'],
                                   cwd=root, env=env, stdout=log, stderr=log)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=2) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Isolated test server failed to start')
                    try:
                        if (await client.get(base+'/api/state')).is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(.1)
                else:
                    raise TimeoutError('Isolated test server did not become ready')
            await check(base)
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, timeout=200)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise


asyncio.run(main())
