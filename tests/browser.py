"""Desktop/mobile checks; optional actual hosted run through the browser button."""
import argparse
import asyncio
import getpass
import io
import json
from pathlib import Path
import sys
import time

from PIL import Image, ImageStat
from playwright.async_api import async_playwright


async def main(args, key):
    output = Path('artifacts/browser')
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        checks = []
        for name, width, height in [('desktop', 1440, 1100), ('mobile', 390, 844)]:
            context = await browser.new_context(viewport={'width': width, 'height': height})
            page = await context.new_page()
            errors = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            await page.goto(args.base)
            await page.wait_for_function("() => document.querySelector('#anatomy').dataset.ready === 'true'", timeout=120000)
            await page.click('#begin')
            await page.wait_for_function("() => Number(document.querySelector('#anatomy').dataset.loadedImages) === 9", timeout=30000)
            await page.wait_for_timeout(2500)
            a = await page.locator('#anatomy').screenshot()
            await page.wait_for_timeout(1500)
            b = await page.locator('#anatomy').screenshot()
            assert a != b, 'Scene did not move'
            stats = ImageStat.Stat(Image.open(io.BytesIO(b)).convert('RGB'))
            assert max(stats.stddev) > 10, 'Blank canvas'
            assert await page.evaluate('() => document.documentElement.scrollWidth <= innerWidth'), 'Horizontal overflow'
            await page.click('#fresh')
            await page.locator('#key-dialog').screenshot(path=str(output / (name+'-key-dialog.png')))
            assert await page.locator('#api-key').get_attribute('type') == 'password'
            await page.click('#key-close')
            await page.screenshot(path=str(output / (name+'.png')), full_page=True)
            assert not errors, errors
            checks.append({'viewport': name, 'canvas_nonblank': True, 'scene_moves': True, 'nine_images': True, 'errors': errors})
            if args.live and name == 'desktop':
                await page.click('#fresh')
                await page.fill('#api-key', key)
                await page.click('#key-start')
                key = None
                await page.wait_for_function('() => state.live && !!state.liveRunId', timeout=30000)
                assert await page.input_value('#api-key') == ''
                assert await page.evaluate('() => localStorage.length === 0 && sessionStorage.length === 0')
                deadline = time.monotonic() + 7200
                last = ''
                while time.monotonic() < deadline:
                    status = await page.evaluate("async () => (await fetch('/api/live?run_id='+encodeURIComponent(state.liveRunId))).json()")
                    progress = status.get('progress', '')
                    if progress != last:
                        print(progress, flush=True)
                        last = progress
                    if not status.get('running'):
                        break
                    await asyncio.sleep(3)
                else:
                    raise RuntimeError('Hosted run timed out')
                for suffix in ('evidence', 'trace', 'audit'):
                    data = await page.evaluate("async suffix => (await fetch('/api/live/'+suffix+'?run_id='+encodeURIComponent(state.liveRunId))).text()", suffix)
                    (output / ('live-'+suffix+('.json' if suffix=='evidence' else '.jsonl'))).write_text(data.rstrip()+'\n')
                assert not status.get('error'), status.get('error')
                result = json.loads((output / 'live-evidence.json').read_text())
                assert result['metrics']['after']['tiles'] == 180
                assert result['test_feedback'] == 0 and result['public_policy_state_unchanged']
                print(json.dumps(result['metrics'], indent=2), flush=True)
                checks.append({'hosted_run_complete': True, 'metrics': result['metrics'], 'key_input_cleared': True, 'no_browser_storage': True})
            await context.close()
        await browser.close()
        (output / 'checks.json').write_text(json.dumps(checks, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8793')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    key = getpass.getpass('Neuroadapt API key (hidden): ').strip() if args.live else None
    asyncio.run(main(args, key))
