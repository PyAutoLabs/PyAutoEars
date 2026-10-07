"""Generated surfaces only; no decisions, writes to GitHub or task state."""
from __future__ import annotations

import html
import importlib.util
import json
import re
from datetime import timedelta
from pathlib import Path

from .collect import line, now, utc, validate
from .presentation import CHECKIN, CSS, copy_button, pill, progress, waiting_label


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def presentation(brain):
    theme = load_module(Path(brain) / "board/_theme.py", "ears_theme")
    state = load_module(Path(brain) / "board/_state.py", "ears_state")
    # Compatibility fallback when paired with a Brain checkout before Ears integration.
    theme.ORGANS.setdefault("ears", {
        "organ": "Ears", "tagline": "Listen. Understand. Follow through.",
        "ink_light": "#96520b", "ink_dark": "#ffc078", "glow": "#ffc078",
        "hero": ("#36200d", "#080503"),
    })
    theme.MARKS.setdefault("ears", '<path d="M15 22c-5-18 23-23 24-4 0 9-10 10-11 19-1 8-12 8-13 0m6-17c-1-9 11-10 12-2 0 5-8 6-8 12"/>')
    return theme, state


def render(snapshot, config, brain, rendered_at=None, plans=()):
    validate(snapshot)
    theme, contract = presentation(brain)
    current = utc(rendered_at or now())
    generated = utc(snapshot["generated"])
    fresh_until = generated + timedelta(hours=config["fresh_hours"])
    stale = current > fresh_until or generated > current + timedelta(minutes=5)
    rows = snapshot["conversations"]
    receipts = snapshot["receipts"]
    incomplete = [x for x in receipts if x["status"] not in {"complete", "excluded"}]
    unknown = [r for r in rows if r["awaiting_response"] is None or r["coverage"] != "complete"]
    attention = [r for r in rows if r["awaiting_response"] or r["review_requested"]]
    attention.sort(key=lambda r: r.get("waiting_since") or snapshot["generated"])
    delivery = snapshot.get("follow_through", [])
    owed = [r for r in delivery if r["update_owed"] is True]
    delivery_unknown = [r for r in delivery if r["state"] == "unknown"]
    status = "stale" if stale else "yellow" if incomplete or unknown or attention or owed or delivery_unknown else "green"
    if not receipts or all(r["status"] in {"unavailable", "excluded"} for r in receipts):
        status = "grey"
    headline = f"{len(attention)} need attention · {len(unknown)} unknown · {len(incomplete)} source gaps · {len(owed)} updates owed · {len(delivery_unknown)} delivery unknown"
    if stale:
        headline = "STALE — " + headline
    items = []
    for row in attention + [r for r in unknown if r not in attention]:
        prompt = theme.portable_prompt(f"/community triage {row['url']}")
        items.append({"id": row["id"], "severity": "yellow", "text": line(row["title"]),
                      "url": row["url"], "prompt": prompt,
                      "state": "unknown" if row in unknown else "action_required",
                      "actions": [{"id": "triage", "kind": "prompt", "label": "Triage",
                                   "target": prompt, "safety": "read_only"}]})
    for row in ([] if stale else owed):
        prompt = theme.portable_prompt(f"/community triage {row['discussion']} — verify delivery evidence and draft a contributor update for approval; do not post")
        items.append({"id": "delivery:" + row["discussion"], "severity": "yellow",
                      "text": "Contributor update owed", "url": row["discussion"], "prompt": prompt,
                      "state": "action_required"})
    if incomplete or not receipts:
        items.append({"id": "coverage", "severity": "yellow", "text": "Listening coverage is incomplete",
                      "state": "unknown", "url": config["pages_url"] + "#coverage"})
    if stale:
        items.append({"id": "freshness", "severity": "yellow", "text": "Snapshot is stale; refresh before judging the queue",
                      "state": "stale"})
    state = contract.build_state("ears", config["repo"], status, headline,
                                 snapshot["generated"], config["pages_url"], items,
                                 valid_until=fresh_until.isoformat())
    page, markdown = render_page(snapshot, theme, headline, stale, fresh_until,
                                 attention, unknown, delivery, receipts, plans, config)
    badge = {"schemaVersion": 1, "label": "ears", "message": headline,
             "color": {"green": "green", "yellow": "yellow", "stale": "lightgrey", "grey": "lightgrey"}[status]}
    return {"index.html": page, "dashboard.html": page, "dashboard.md": markdown,
            "state.json": json.dumps(state, indent=2) + "\n",
            "badge.json": json.dumps(badge, indent=2) + "\n"}


def render_page(snapshot, theme, headline, stale, fresh_until, attention, unknown,
                delivery, receipts, plans, config):
    esc = html.escape
    rows = snapshot['conversations']
    linked = {d['discussion']: d for d in delivery}
    gaps = sum(r['status'] not in {'complete', 'excluded'} for r in receipts)
    navigation = [
        {"href": "#attention", "label": "Need attention", "count": len(attention)},
        {"href": "#coverage", "label": "Source gaps", "count": gaps},
        {"href": "#activity", "label": "Recent activity"},
    ]
    body = [theme.hero('ears', 'Community board', navigation=navigation)]
    body.append('<p id="freshness" role="status"' + ('' if stale else ' hidden') +
                '>These figures may be out of date. Use the community check-in below to update them.</p>')
    work_links = [{"label": "Open Community Hub ↗",
                   "href": "https://github.com/orgs/PyAutoLabs/discussions"}]
    repository = config["repo"]
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        work_links.append({"label": repository, "href": "https://github.com/" + repository})
    checkin = theme.portable_prompt(CHECKIN)
    body.append(theme.orchestration_panel("ears", "", "", CHECKIN,
                work_links=work_links, copy_label="Copy community check-in", organ="ears",
                refreshed_at=(snapshot.get("generated")
                              if any(r["status"] == "complete" for r in receipts)
                              and all(r["status"] in {"complete", "excluded"} for r in receipts)
                              else None),
                refresh_url=(f"https://github.com/{repository}/actions/workflows/pages.yml"
                             if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) else None)))
    md = ['# PyAutoEars', '', headline, '', '## Community check-in', '', '```text', checkin, '```', '']

    def section(title, key, selected, empty):
        body.append(f'<section id="{key}"><div class="section-head"><h2>{esc(title)} '
                    f'<span class="section-count">{len(selected)}</span></h2></div>')
        md.extend(['## ' + title, '', '| Topic | Repository | Author | Type | Progress | Response |',
                   '| --- | --- | --- | --- | --- | --- |'])
        if not selected:
            body.append(f'<p class="empty">{esc(empty)}</p></section>')
            md.extend([empty, ''])
            return
        body.append(f'<div class="table-wrap" role="region" aria-label="{esc(title)}" tabindex="0">'
                    '<table class="community"><thead><tr><th scope="col">Conversation / repository</th>'
                    '<th scope="col">Author</th><th scope="col">Progress</th><th scope="col">Response</th>'
                    '<th scope="col">Actions</th></tr></thead><tbody>')
        for row in selected:
            d = linked.get(row['url'])
            label, tone = progress(row, d, stale, plans)
            timing = waiting_label(row, snapshot['generated'])
            kind = {'issue': 'Issue', 'pr': 'PR', 'discussion': 'Discussion'}[row['kind']]
            prompt = theme.portable_prompt(f"/community triage {row['url']}")
            details = '<p><a href="' + esc(row['url'], quote=True) + '">Open ' + kind.lower() + ' ↗</a></p>'
            if row.get('waiting_since'):
                details += '<p>Waiting since <time datetime="' + esc(row['waiting_since'], quote=True) + '">' + esc(utc(row['waiting_since']).strftime('%d %b %Y, %H:%M UTC')) + '</time></p>'
            if stale:
                details += '<p>Response and progress observations are stale. Refresh before acting.</p>'
            if row['category']:
                details += '<p>Category: ' + esc(row['category']) + '</p>'
            if row['feedback_report']:
                details += '<p>Feedback report (format marker only)</p>'
            for gap in row['gaps']:
                details += '<p>' + esc(line(gap)) + '</p>'
            if d:
                details += '<p>Delivery: ' + esc('unknown (stale observation)' if stale else d['state'].replace('_', ' ')) + '</p>'
                for evidence in d['evidence']:
                    details += '<p><a href="' + esc(evidence['url'], quote=True) + '">' + esc(evidence['kind'] + ': ' + evidence['url']) + '</a></p>'
                for gap in d['gaps']:
                    details += '<p>' + esc(line(gap)) + '</p>'
                follow = theme.portable_prompt('/community triage ' + row['url'] + ' — verify linked delivery evidence and draft a contributor update for approval; do not post')
                details += copy_button(follow, 'Copy follow-through prompt')
            details += '<details><summary>Triage prompt</summary><pre>' + esc(prompt) + '</pre></details>'
            author = esc(row['author']) if row['author'] else 'Unavailable'
            author_html = '<span class="author">@' + author + '</span>' if row['author'] else '<span class="author-empty">Unavailable</span>'
            note = '<span class="small-note owed-note">contributor update owed</span>' if d and d['update_owed'] is True and not stale else ''
            if label == 'Plan recorded':
                details += '<p>An issued Mind record explicitly links this issue and contains a plan.</p>'
            body.append('<tr><td><details class="topic"><summary>' + esc(row['title']) +
                        '<span class="topic-meta">' + esc(row['repo']) + ' · ' + kind + ' #' + str(row['number']) +
                        '</span></summary><div class="topic-body">' + details + '</div></details></td><td>' + author_html +
                        '</td><td>' + pill(label, tone) + note + '</td><td>' + esc(timing) +
                        ('<span class="small-note">At last observation</span>' if stale else '') +
                        '</td><td><div class="row-actions">' + copy_button(prompt, 'Copy triage prompt') +
                        '<a class="source-action" aria-label="Open conversation on GitHub" title="Open conversation on GitHub" href="' +
                        esc(row['url'], quote=True) + '">↗</a></div></td></tr>')
            md_title = row["title"].replace("[", "&#91;").replace("]", "&#93;")
            values = [f"[{md_title}]({row['url']})", row['repo'], row['author'] or 'Unavailable', kind, label, timing]
            md.append('| ' + ' | '.join(esc(v).replace('|', '&#124;').replace('\n', ' ') for v in values) + ' |')
        body.append('</tbody></table></div></section>')
        md.append('')

    section('Needs your attention', 'attention', attention,
            'No attention items found in the observed data. Check coverage before concluding nobody is waiting.')
    section('Community activity', 'activity', [r for r in rows if r not in attention],
            'No additional conversations in the observed data.')
    body.append('<details><summary>Recurring feedback</summary><p>Planned: evidence-backed themes across independent reports. No themes have been inferred by this collector.</p></details>')
    body.append('<p id="copy-status" role="status" aria-live="polite"></p><pre id="copy-fallback" tabindex="-1" hidden></pre>')
    body.append('<section id="coverage"><h2>Listening coverage</h2><div class="table-wrap" role="region" aria-label="Listening coverage" tabindex="0">'
                '<table class="coverage"><thead><tr><th scope="col">Repository</th><th scope="col">Coverage</th>'
                '<th scope="col">Checked (UTC)</th><th scope="col">Details</th></tr></thead><tbody>')
    md.extend(['## Listening coverage', '', '| Repository | Coverage | Checked | Details |', '| --- | --- | --- | --- |'])
    for r in receipts:
        tone = {'complete': 'green', 'partial': 'amber', 'unavailable': 'purple', 'excluded': 'neutral'}[r['status']]
        date = utc(r['checked_at']).strftime('%d %b %Y, %H:%M')
        gap = '; '.join(line(g) for g in r['gaps']) or ('Public source checked' if r['status'] == 'complete' else 'No public data collected')
        body.append('<tr><td>' + esc(r['repo']) + '</td><td>' + pill(r['status'].title(), tone) + '</td><td><time datetime="' +
                    esc(r['checked_at'], quote=True) + '">' + date + '</time></td><td>' + esc(gap) + '</td></tr>')
        md.append('| ' + ' | '.join(esc(v).replace('|', '&#124;') for v in [r['repo'], r['status'], date, gap]) + ' |')
    if not receipts:
        body.append('<tr><td colspan="4">Coverage unknown — no source receipts.</td></tr>')
    body.append('</tbody></table></div></section>')
    script = 'const expires = ' + json.dumps(fresh_until.isoformat()) + ';\n' + SCRIPT
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>PyAutoEars community board</title><style>' + theme.css('ears') + CSS + '</style></head><body><main>' +
            '\n'.join(body) + '</main><script>' + theme.JS + script + '</script></body></html>')
    return page, '\n'.join(md) + '\n'


SCRIPT = r"""
function checkFreshness() {
  if (Date.now() > Date.parse(expires)) {
    document.getElementById('freshness').hidden = false;
    document.querySelectorAll('.community .badge').forEach(b => {b.textContent = 'Refresh needed'; b.className = 'badge neutral'});
    document.querySelectorAll('.owed-note').forEach(n => n.hidden = true);
  }
}
checkFreshness();
window.addEventListener('pageshow', checkFreshness);
document.addEventListener('visibilitychange', checkFreshness);
document.querySelectorAll('button[data-copy]').forEach(button => {
  button.addEventListener('click', async () => {
    const status = document.getElementById('copy-status');
    const fallback = document.getElementById('copy-fallback');
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      status.textContent = 'Prompt copied'; fallback.hidden = true;
    } catch (_) {
      status.textContent = 'Copy unavailable. Select the prompt below.';
      fallback.textContent = button.dataset.copy; fallback.hidden = false; fallback.focus();
      const range = document.createRange(); range.selectNodeContents(fallback);
      const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    }
  });
});
"""
