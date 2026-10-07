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
    snapshot['conversations'][1]['title'] = 'Add a tutorial for the new fitting workflow'
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
            assert not page.locator('#freshness').is_visible()
            assert page.locator('.orchestration-panel a').count() == 2
            assert page.locator('#unknown, #follow-through').count() == 0
            for link in page.locator('a[href^="#"]').all():
                assert page.locator(link.get_attribute('href')).count() == 1
            page.get_by_role('link', name='Open Community Hub').focus()
            assert page.get_by_role('link', name='Open Community Hub').evaluate('(e) => e === document.activeElement')
            page.locator('#orchestration-ears-direction').fill('Prioritize unanswered questions')
            checkin = page.get_by_role('button', name='Copy community check-in')
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
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
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
