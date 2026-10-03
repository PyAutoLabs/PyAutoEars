"""Generated surfaces only; no decisions, writes to GitHub or task state."""
from __future__ import annotations

import html
import importlib.util
import json
from datetime import timedelta
from pathlib import Path

from .collect import line, now, utc, validate


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


def render(snapshot, config, brain, rendered_at=None):
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
    esc = html.escape
    body = [theme.hero("ears", "Community board"), f'<p role="status">{esc(headline)}</p>',
            f'<p class="muted">Observed {esc(snapshot["generated"])}. Response states are heuristics; accepted does not mean delivered.</p>',
            '<p><a href="https://github.com/orgs/PyAutoLabs/discussions">Open community hub</a></p>']
    md = ["# PyAutoEars", "", headline, "", f"Observed: {snapshot['generated']}", ""]

    def section(title, selected, empty):
        body.append(f"<section><h2>{esc(title)}</h2>")
        md.extend(["## " + title, ""])
        if not selected:
            body.append(f"<p>{esc(empty)}</p>")
            md.extend([empty, ""])
        for row in selected:
            since = row.get("waiting_since")
            timing = f"Waiting since {since}" if since else "Response age unknown" if row["awaiting_response"] is None else "Ours to watch"
            prompt = theme.portable_prompt(f"/community triage {row['url']}")
            body.append('<article class="conversation"><h3><a href="' + esc(row["url"], quote=True) + '">' +
                        esc(row["title"]) + '</a></h3><p>' + esc(row["repo"] + " · " + timing) + '</p>' +
                        ('<p>Feedback report (format marker only)</p>' if row.get("feedback_report") else '') +
                        '<button type="button" data-copy="' + esc(prompt, quote=True) + '">Copy triage prompt</button>' +
                        '<details><summary>Prompt</summary><pre>' + esc(prompt) + '</pre></details></article>')
            md.extend([f"- [{esc(row['title']).replace('[', '&#91;').replace(']', '&#93;')}]({row['url']}) — {timing}",
                       "", "```text", prompt, "```", ""])
        body.append("</section>")

    section("Needs your attention", attention,
            "No attention items found in the observed data. Check coverage before concluding nobody is waiting.")
    section("Unknown response state", unknown, "No unknown conversation states in the observed data.")
    section("Community activity", [r for r in rows if r not in attention and r not in unknown],
            "No additional conversations in the observed data.")
    body.append('<section id="coverage"><h2>Listening coverage</h2><ul>')
    md.extend(["## Listening coverage", ""])
    for r in receipts:
        text = f"{r['repo']}: {r['status']}"
        if r["gaps"]:
            text += " — " + "; ".join(line(g) for g in r["gaps"])
        body.append("<li>" + esc(text) + "</li>")
        md.append("- " + esc(text))
    body.append('</ul><p>Discussion comments and replies are read separately. Failed reads and pagination limits remain explicit coverage gaps; accepted answers do not establish delivery.</p></section>')
    body.append('<section><h2>Following through</h2><p>Explicit maintainer links only. Missing links mean unknown; settled conversations stay settled.</p>')
    md.extend(["", "## Following through", ""])
    if not delivery:
        body.append('<p>No delivery evidence in this snapshot.</p>')
        md.append('No delivery evidence in this snapshot.')
    for row in delivery:
        label = 'unknown (stale observation)' if stale else row['state'].replace('_', ' ')
        if row['update_owed'] is True and not stale:
            label += ' — contributor update owed'
        body.append('<article><h3><a href="' + esc(row['discussion'], quote=True) + '">Discussion</a>: ' + esc(label) + '</h3><ul>')
        md.append('- ' + row['discussion'] + ': ' + label)
        for evidence in row['evidence']:
            body.append('<li><a href="' + esc(evidence['url'], quote=True) + '">' + esc(evidence['kind'] + ': ' + evidence['url']) + '</a></li>')
            md.append('  - ' + evidence['url'])
        body.append('</ul>')
        for gap in row['gaps']:
            body.append('<p>' + esc(gap) + '</p>')
        prompt = theme.portable_prompt('/community triage ' + row['discussion'] + ' — verify linked delivery evidence and draft a contributor update for approval; do not post')
        body.append('<button type="button" data-copy="' + esc(prompt, quote=True) + '">Copy follow-through prompt</button><details><summary>Prompt</summary><pre>' + esc(prompt) + '</pre></details></article>')
        md.extend(['', '```text', prompt, '```', ''])
    body.append('</section>')
    for title, message in [("Recurring feedback", "Planned: evidence-backed themes across independent reports. No themes have been inferred by this collector.")]:
        body.append(f"<section><h2>{title}</h2><p>{message}</p></section>")
        md.extend(["", "## " + title, "", message, ""])
    body.append('<p id="copy-status" role="status" aria-live="polite"></p>')
    script = 'const expires = ' + json.dumps(fresh_until.isoformat()) + ''';
    if (Date.now() > Date.parse(expires)) {
      document.querySelector('p[role="status"]').textContent = 'STALE — refresh required before judging the queue';
    }
    document.querySelectorAll('button[data-copy]').forEach(button => {
      button.addEventListener('click', async () => {
        const status = document.getElementById('copy-status');
        try { await navigator.clipboard.writeText(button.dataset.copy); status.textContent = 'Prompt copied'; }
        catch (_) { status.textContent = 'Copy unavailable. Open Prompt and select the text.'; }
      });
    });'''
    css = theme.css("ears") + '\nbody{max-width:1000px;margin:auto;padding:16px} .conversation{padding:12px 0;border-bottom:1px solid #8885} pre{white-space:pre-wrap;overflow-wrap:anywhere} h3,a,li,p{overflow-wrap:anywhere} button{min-height:44px;cursor:pointer} section{margin:28px 0}'
    page = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PyAutoEars community board</title><style>' + css + '</style></head><body><main>' + '\n'.join(body) + '</main><script>' + script + '</script></body></html>'
    badge = {"schemaVersion": 1, "label": "ears", "message": headline,
             "color": {"green": "green", "yellow": "yellow", "stale": "lightgrey", "grey": "lightgrey"}[status]}
    return {"index.html": page, "dashboard.html": page, "dashboard.md": "\n".join(md),
            "state.json": json.dumps(state, indent=2) + "\n",
            "badge.json": json.dumps(badge, indent=2) + "\n"}
