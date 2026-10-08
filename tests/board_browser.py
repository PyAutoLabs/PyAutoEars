"""Real browser smoke on synthetic data only; never deploy this fixture."""
import functools
from datetime import datetime, timedelta, timezone
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from test_ears import BRAIN, CONFIG, STAMP, board, fixture
from test_followthrough import delivery_snapshot
from test_closed_followups import candidate_snapshot


def main():
    output = Path("_site/browser-fixture").resolve()
    output.mkdir(parents=True, exist_ok=True)
    snapshot = fixture()
    linked = delivery_snapshot()
    snapshot["conversations"].extend(linked["conversations"])
    snapshot["follow_through"] = linked["follow_through"]
    stamp = datetime.now(timezone.utc)
    snapshot['generated'] = stamp.isoformat()
    for receipt in snapshot['receipts']:
        receipt['checked_at'] = stamp.isoformat()
    # Use realistic public-metadata lengths without making live network reads.
    snapshot['conversations'][0]['title'] = 'Help configuring multi-band galaxy models'
    snapshot['conversations'][0]['waiting_since'] = (stamp - timedelta(days=3)).isoformat()
    snapshot['conversations'][0]['updated_at'] = stamp.isoformat()
    snapshot['conversations'][1]['title'] = 'Add a tutorial for the new fitting workflow'
    followup = candidate_snapshot()['conversations'][0]
    followup.update(number=13, id='example/hub/discussions/13',
                    url='https://github.com/example/hub/discussions/13',
                    title='New request on a closed discussion',
                    waiting_since=(stamp - timedelta(days=1)).isoformat())
    followup['follow_up'].update(since=followup['waiting_since'],
                                url=followup['url'] + '#discussioncomment-42')
    snapshot['conversations'].append(followup)
    for name, value in board.render(snapshot, CONFIG, BRAIN).items():
        (output / name).write_text(value)
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(output)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                for scheme in ("light", "dark"):
                    page.emulate_media(color_scheme=scheme)
                    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (width, scheme)
                    page.screenshot(path=str(output / f"synthetic-{width}-{scheme}.png"), full_page=True)
            # Major sections start collapsed (PyAutoBrain#490); the nav card reveals its target.
            sections = page.locator('details.board-section')
            assert sections.count() == 3
            assert sections.evaluate_all('(nodes) => nodes.every((d) => !d.open)')
            assert not page.locator('#attention').is_visible()
            page.locator('.board-nav-card[href="#attention"]').click()
            page.wait_for_function("document.getElementById('attention').closest('details.board-section').open")
            followup_topic = page.locator('#attention .topic').filter(has_text='New request on a closed discussion')
            followup_topic.locator(':scope > summary').click()
            assert 'Closed · Answered' in followup_topic.inner_text()
            assert 'permission' in followup_topic.inner_text()
            assert followup_topic.get_by_role('link', name='Read follow-up').get_attribute('href').endswith('#discussioncomment-42')
            assert not page.locator('#freshness').is_visible()
            assert page.locator('.orchestration-links a').count() == 2
            update = page.locator('.orchestration-panel [data-refresh-link]')
            assert update.count() == 1
            assert update.get_attribute('href') == f"https://github.com/{CONFIG['repo']}/actions/workflows/pages.yml"
            assert page.locator('#unknown, #follow-through').count() == 0
            for link in page.locator('a[href^="#"]').all():
                assert page.locator(link.get_attribute('href')).count() == 1
            page.get_by_role('link', name='Open Community Hub').focus()
            assert page.get_by_role('link', name='Open Community Hub').evaluate('(e) => e === document.activeElement')
            page.locator('#orchestration-ears-direction').fill('Prioritize unanswered questions')
            checkin = page.get_by_role('button', name='Copy check-in prompt')
            checkin.click()
            page.wait_for_function("navigator.clipboard.readText().then(t => t.includes('Optional direction (user context):\\nPrioritize unanswered questions'))")
            assert '\n\nOptional direction (user context):' in page.evaluate('navigator.clipboard.readText()')
            assert 'Prioritize unanswered questions' in page.locator('#orchestration-ears-prompt').input_value()
            summary = page.locator('#attention .topic summary').first
            summary.focus()
            page.keyboard.press('Enter')
            assert page.locator('#attention .topic').first.get_attribute('open') is not None
            button = page.get_by_role("button", name="Copy triage prompt").first
            button.click()
            page.wait_for_function("document.getElementById('copy-status').textContent === 'Prompt copied'")
            copied = page.evaluate("navigator.clipboard.readText()")
            assert "community" in copied and "https://github.com/example/lib/issues/1" in copied
            page.locator('.board-nav-card[href="#activity"]').click()
            page.wait_for_function("document.getElementById('activity').closest('details.board-section').open")
            page.locator('#activity .topic summary').first.click()
            follow = page.get_by_role("button", name="Copy follow-through prompt").first
            follow.click()
            page.wait_for_function("navigator.clipboard.readText().then(t => t.includes('do not post'))")
            assert "example/hub/discussions/1" in page.evaluate("navigator.clipboard.readText()")
            page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw Error('denied')}}})")
            button.click()
            page.wait_for_function("document.getElementById('copy-status').textContent.startsWith('Copy unavailable')")
            assert page.locator('#copy-fallback').is_visible()
            assert 'https://github.com/example/lib/issues/1' in page.locator('#copy-fallback').inner_text()
            assert page.evaluate('window.getSelection().toString()') == page.locator('#copy-fallback').inner_text()
            for width in (390, 1280):
                page.set_viewport_size({'width': width, 'height': 900})
                for scheme in ('light', 'dark'):
                    page.emulate_media(color_scheme=scheme)
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    assert page.locator('#attention th', has_text='Updated').count() == 1
                    assert page.locator('#activity th', has_text='Updated').count() == 1
                    assert page.locator('.topic-meta').count() == 0
                    assert page.get_by_text('Recurring feedback', exact=True).count() == 0
                    assert page.locator('.topic-body strong', has_text='Delivery:').first.is_visible()
                    page.screenshot(path=str(output / f'expanded-{width}-{scheme}.png'), full_page=True)
            # Re-opening an expired page must suppress current delivery claims.
            page.evaluate("Date.now = () => Date.parse(expires) + 1; window.dispatchEvent(new Event('pageshow'))")
            assert page.locator('#freshness').is_visible()
            assert not page.locator('.owed-note').first.is_visible()
            assert page.locator('#activity .badge').first.inner_text() == 'Refresh needed'
            assert not errors, errors
            (output / "browser-result.json").write_text(json.dumps({"widths": [390, 1280], "themes": ["light", "dark"], "copy": "success and denial passed", "page_errors": errors}))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
