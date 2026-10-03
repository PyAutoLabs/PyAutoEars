"""Real browser smoke on synthetic data only; never deploy this fixture."""
import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from test_ears import BRAIN, CONFIG, STAMP, board, fixture


def main():
    output = Path("_site/browser-fixture").resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name, value in board.render(fixture(), CONFIG, BRAIN, rendered_at=STAMP).items():
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
            button = page.get_by_role("button", name="Copy triage prompt").first
            button.click()
            page.wait_for_function("document.getElementById('copy-status').textContent === 'Prompt copied'")
            copied = page.evaluate("navigator.clipboard.readText()")
            assert "community" in copied and "https://github.com/example/lib/issues/1" in copied
            page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw Error('denied')}}})")
            button.click()
            page.wait_for_function("document.getElementById('copy-status').textContent.startsWith('Copy unavailable')")
            assert not errors, errors
            (output / "browser-result.json").write_text(json.dumps({"widths": [390, 1280], "themes": ["light", "dark"], "copy": "success and denial passed", "page_errors": errors}))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
