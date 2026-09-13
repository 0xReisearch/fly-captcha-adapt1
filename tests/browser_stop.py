"""Use a prompted visitor key, start briefly, stop, and verify the request count settles."""
import argparse
import asyncio
import getpass
import json
from pathlib import Path

from playwright.async_api import async_playwright


async def main(base, key):
    output = Path('artifacts/stop-check')
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(base)
        assert await page.locator('#fresh').inner_text() == 'Use my API key'
        assert (await page.locator('#fresh').bounding_box())['y'] < 900
        assert (await page.request.post(base+'/api/start', headers={'origin': base}, data={})).status == 422
        await page.click('#fresh')
        await page.fill('#api-key', key)
        await page.click('#key-start')
        key = None
        await page.wait_for_function('() => state.live && !!state.liveRunId', timeout=30000)
        assert await page.input_value('#api-key') == ''
        assert await page.evaluate('() => localStorage.length === 0 && sessionStorage.length === 0')
        await page.wait_for_function('() => state.trials.some(r => r.phase === "training" && r.feedback_count >= 2) || state.liveDone', timeout=300000)
        assert not await page.evaluate('() => state.liveDone'), 'Run ended before stop test'
        await page.evaluate('() => window.scrollTo(0, 1000)')
        assert (await page.locator('#stop-run').bounding_box())['y'] < 100
        await page.click('#stop-run')
        await page.wait_for_function('() => state.stopped && state.liveDone', timeout=120000)
        await page.screenshot(path=str(output/'stopped.png'))
        async def snapshot():
            return await page.evaluate("async () => {const q='?run_id='+encodeURIComponent(state.liveRunId);return {live:await (await fetch('/api/live'+q)).json(),audit:await (await fetch('/api/live/audit'+q)).text(),result:await (await fetch('/api/live/evidence'+q)).json()}}")
        first = await snapshot()
        await asyncio.sleep(5)
        second = await snapshot()
        assert first == second, 'Requests or outcomes changed after stopped confirmation'
        assert second['result']['status'] == 'stopped'
        outsider = await browser.new_context()
        check = await outsider.request.get(base+'/api/live?run_id='+await page.evaluate('() => state.liveRunId'))
        assert check.status == 404
        await outsider.close()
        await page.reload()
        await page.wait_for_function('() => state.stopped && state.liveDone', timeout=30000)
        assert not errors, errors
        report = {'stopped': True, 'no_further_calls_after_stop': True, 'stopped_after_feedbacks': second['live']['events'][-1]['feedback_count'],
                  'api_calls': len(second['audit'].strip().splitlines()), 'own_key_required': True,
                  'key_input_cleared': True, 'no_browser_storage': True, 'other_visitor_denied': True,
                  'stop_visible_when_scrolled': True, 'stopped_state_survives_reload': True, 'javascript_errors': errors}
        (output/'checks.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
        await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='https://fly.reilabs.org')
    args = parser.parse_args()
    asyncio.run(main(args.base.rstrip('/'), getpass.getpass('Visitor Neuroadapt API key (hidden): ').strip()))
