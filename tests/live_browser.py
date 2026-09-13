"""Browser checks for BYOK live hosting. --live consumes production API quota."""
import argparse
import asyncio
import getpass
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image
from playwright.async_api import async_playwright


async def check(args, key):
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 1100})
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        await page.goto(args.base)
        await page.locator('#begin').wait_for(state='visible')
        await page.wait_for_function("() => !document.querySelector('#begin').disabled", timeout=90000)
        await page.locator('#begin').click()
        await page.wait_for_timeout(3000)
        await page.screenshot(path=str(out/'recording-desktop.png'), full_page=True)
        await page.locator('#fresh').click()
        await page.wait_for_url('**/live')
        await page.wait_for_function("() => document.querySelector('#scene').dataset.ready==='true'", timeout=90000)
        await page.wait_for_function("() => document.querySelector('#deployment').textContent.includes('YOUR KEY')")
        await page.locator('#start').click()
        await page.locator('#api-key').fill('temporary-dialog-check-not-a-key')
        await page.locator('#key-close').click()
        assert await page.locator('#api-key').input_value() == ''
        assert await page.evaluate('localStorage.length===0 && sessionStorage.length===0')
        assert (await page.request.post(args.base+'/api/start', headers={'Origin': args.base}, data={})).status == 422
        assert (await page.request.post(args.base+'/api/start', headers={'Origin': 'https://other.example'}, data={})).status == 403
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_timeout(1000)
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.screenshot(path=str(out/'live-mobile.png'), full_page=True)
        checks = {'recording_without_key': True, 'key_dialog_clears': True, 'browser_storage_empty': True,
                  'missing_key_rejected': True, 'cross_origin_rejected': True, 'mobile_no_overflow': True}
        if args.live:
            await page.set_viewport_size({'width': 1440, 'height': 1100})
            await page.locator('#start').click()
            await page.locator('#api-key').fill(key)
            await page.locator('#key-start').click()
            key = ''
            assert await page.locator('#api-key').input_value() == ''
            deadline = time.monotonic()+6800
            previous = None
            live_shot = False
            while time.monotonic() < deadline:
                state = await (await page.request.get(args.base+'/api/state')).json()
                progress = (state['status'], len(state['history']))
                if progress != previous:
                    print(json.dumps({'status': progress[0], 'choices': progress[1],
                                      'feedbacks': (state.get('record') or {}).get('feedback_count', 0)}), flush=True)
                    previous = progress
                if not live_shot and (state.get('record') or {}).get('feedback_count', 0) >= 3:
                    pixels = await page.locator('#scene').screenshot()
                    assert np.asarray(Image.open(io.BytesIO(pixels))).std() > 15
                    await page.screenshot(path=str(out/'live-training.png'), full_page=True)
                    assert int(await page.locator('#scene').get_attribute('data-active-neurons')) > 100
                    first = await page.locator('#scene').get_attribute('data-fly-position')
                    await page.wait_for_timeout(2500)
                    assert first != await page.locator('#scene').get_attribute('data-fly-position')
                    live_shot = True
                if state['status'].startswith('Failed') or state['status'] == 'Stopped':
                    (out/'incomplete.json').write_text(json.dumps({'status': state['status'], 'history': state['history']}, indent=2)+'\n')
                    for name in ('trace.jsonl', 'core-api-trace.jsonl', 'domain.json', 'configuration.json'):
                        response = await page.request.get(args.base+'/api/download/'+name)
                        if response.ok:
                            (out/name).write_bytes(await response.body())
                    await page.request.post(args.base+'/api/end', headers={'Origin': args.base})
                    raise RuntimeError(state['status'])
                if state.get('trained') and not state['running']:
                    break
                await asyncio.sleep(15)
            else:
                raise TimeoutError('Production run did not finish')
            result = state['results']
            assert result['test_feedback'] == 0 and result['metrics']['after']['tiles'] == 180
            assert result['fly_feedbacks'] == 360 and result['graph_fixed']
            for name in ('results.json', 'trace.jsonl', 'core-api-trace.jsonl', 'domain.json', 'configuration.json'):
                response = await page.request.get(args.base+'/api/download/'+name)
                assert response.ok
                (out/name).write_bytes(await response.body())
            other = await browser.new_context()
            other_page = await other.new_page()
            await other_page.goto(args.base+'/live')
            assert not (await (await other_page.request.get(args.base+'/api/state')).json())['running']
            assert (await other_page.request.get(args.base+'/api/download/results.json')).status == 404
            assert (await other_page.request.post(args.base+'/api/stop', headers={'Origin': args.base})).status == 404
            await other.close()
            await page.locator('#next').click()
            await page.locator('#watch').wait_for(state='visible')
            await page.locator('#watch').click()
            await page.wait_for_function("() => document.querySelector('#status').textContent==='Round complete'", timeout=180000)
            practice = await (await page.request.get(args.base+'/api/state')).json()
            assert practice['results'] == result
            assert practice['practice']['result']['fly_unchanged'] and practice['practice']['result']['core_unchanged']
            await page.screenshot(path=str(out/'live-practice-complete.png'), full_page=True)
            await page.locator('#next').click()
            await page.locator('#watch').wait_for(state='visible')
            await page.locator('#watch').click()
            await page.wait_for_function("() => !document.querySelector('#stop').disabled")
            await page.locator('#stop').click()
            await page.wait_for_function("() => document.querySelector('#status').textContent==='Stopped'", timeout=180000)
            stopped = await (await page.request.get(args.base+'/api/state')).json()
            await page.wait_for_timeout(2000)
            later = await (await page.request.get(args.base+'/api/state')).json()
            assert stopped['cursor'] == later['cursor'] and not later['running'] and later['trained']
            response = await page.request.get(args.base+'/api/download/practice.jsonl')
            assert response.ok
            (out/'practice.jsonl').write_bytes(await response.body())
            await page.locator('#forget').click()
            await page.wait_for_function("() => document.querySelector('#status').textContent==='Your key. Your fly.'")
            assert (await page.request.get(args.base+'/api/download/results.json')).status == 404
            checks.update(full_production_run=result['metrics'], live_neural_canvas=True, visitor_isolation=True,
                          frozen_practice=True, stop_confirmed=True, forget_releases_session=True)
        assert not errors, errors
        checks['javascript_errors'] = errors
        (out/'browser-checks.json').write_text(json.dumps(checks, indent=2)+'\n')
        print(json.dumps(checks), flush=True)
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8795')
    parser.add_argument('--output', default='artifacts/hosted-live-browser')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    key = getpass.getpass('Your production key (hidden): ').strip() if args.live else ''
    asyncio.run(check(args, key))
