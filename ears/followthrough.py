"""Read explicit delivery links; never persist task state or source bodies."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote, unquote

from .collect import ReadError, human, pages, utc

LINK = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(issues|pull|releases/tag)/([A-Za-z0-9_.%/-]+)\Z")
LABEL = re.compile(r"^Delivery-(issue|PR|release|revert|update):\s*(https://github\.com/\S+)\s*$", re.M)
STATES = {"accepted", "in_development", "merged_unreleased", "available", "declined", "unknown"}


def link(url, kind=None):
    m = LINK.fullmatch(url) if isinstance(url, str) else None
    if not m or '..' in unquote(m[3]).split('/'):
        raise ValueError("invalid delivery link")
    repo, path, number = m.groups()
    if path != 'releases/tag' and (not number.isdigit() or int(number) < 1):
        raise ValueError("invalid delivery number")
    actual = {'issues': 'issue', 'pull': 'PR', 'releases/tag': 'release'}[path]
    if kind and actual != kind:
        raise ValueError("delivery link kind mismatch")
    return repo, actual, number


def pending_releases(mind):
    """Read the existing unresolved obligation keys; never clear or infer them."""
    root = Path(mind)
    if not (root / 'active.md').is_file() or not (root / 'complete').is_dir():
        raise ValueError('Mind pending-release evidence unavailable')
    paths = [root / n for n in ('active.md', 'parked.md', 'planned.md')]
    paths += list((root / 'complete').rglob('*.md'))
    result = set()
    for p in paths:
        if p.is_file():
            for line in p.read_text().splitlines():
                if re.match(r'^\s*- pending-release:', line):
                    result.update(re.findall(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[0-9]+', line))
    return result


def authored(entries, selves):
    return [e for e in entries if human(e.get('user')) and not e.get('deleted_at')
            and e['user']['login'].casefold() in selves]


def links(entries, label):
    result = sorted({url for e in entries for k, url in LABEL.findall(e.get('body') or '') if k == label})
    if len(result) > 100:
        raise ReadError('delivery link budget exceeded')
    return result


def derive(api, discussion, entries, config, complete, pending=None):
    """All required links must be proved; missing evidence never means delivered."""
    result = {'discussion': discussion, 'state': 'unknown', 'update_owed': None,
              'evidence': [], 'gaps': []}
    selves = {x.casefold() for x in config['self_logins']}
    source = authored(entries, selves)
    evidence = {}

    def read(url, kind):
        repo, _, number = link(url, kind)
        meta = api.get(f'repos/{repo}')
        if not isinstance(meta, dict) or meta.get('private') is not False:
            raise ReadError('linked source not verified public')
        endpoint = {'issue': 'issues', 'PR': 'pulls', 'release': 'releases/tags'}[kind]
        raw = api.get(f'repos/{repo}/{endpoint}/{quote(unquote(number), safe="")}')
        if not isinstance(raw, dict):
            raise ReadError('linked evidence unavailable')
        evidence[url] = {'url': url, 'repo': repo, 'kind': kind}
        return repo, number, raw

    try:
        targets = links(source, 'issue')
        if not targets:
            raise ReadError('no explicit maintainer delivery issue link')
        if not complete:
            raise ReadError('Discussion evidence incomplete')
        if any(not isinstance(e.get('body'), str) for e in source):
            raise ReadError('maintainer evidence body unavailable')
        states, delivered = [], {}
        for target in targets:
            repo, number, issue = read(target, 'issue')
            if issue.get('state') not in {'open', 'closed'} or 'pull_request' in issue:
                raise ReadError('invalid target issue state')
            comments, ok, _ = pages(api, f'repos/{repo}/issues/{number}/comments', config['max_pages'])
            if not ok:
                raise ReadError('target issue activity incomplete')
            records = authored([issue] + comments, selves)
            if any(not isinstance(e.get('body'), str) or not isinstance(e.get('user'), dict)
                   for e in [issue] + comments):
                raise ReadError('target activity evidence unavailable')
            if links(records, 'revert'):
                raise ReadError('explicit revert evidence; reassess delivery')
            if issue.get('state') == 'closed' and issue.get('state_reason') == 'not_planned':
                states.append('declined')
                continue
            prs = links(records, 'PR')
            if not prs:
                states.append('accepted' if issue['state'] == 'open' else 'unknown')
                continue
            pr_states = []
            releases = links(records, 'release')
            for url in prs:
                pr_repo, _, pr = read(url, 'PR')
                if type(pr.get('merged')) is not bool or pr.get('state') not in {'open', 'closed'}:
                    raise ReadError('PR state unavailable')
                if not pr['merged']:
                    pr_states.append('in_development' if pr['state'] == 'open' else 'unknown')
                    continue
                if issue['state'] != 'closed' or issue.get('state_reason') != 'completed':
                    raise ReadError('merged work has an unsettled or reopened target issue')
                if pending is None:
                    raise ReadError('Mind pending-release evidence unavailable')
                if url in pending or not releases:
                    pr_states.append('merged_unreleased')
                    continue
                sha = pr.get('merge_commit_sha')
                if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
                    raise ReadError('merge commit unavailable')
                matches = []
                for release_url in releases:
                    rel_repo, tag, release = read(release_url, 'release')
                    if rel_repo != pr_repo:
                        continue
                    if release.get('draft') is not False or release.get('prerelease') is not False:
                        raise ReadError('release is not a published stable release')
                    published = utc(release.get('published_at'))
                    if published < utc(pr.get('merged_at')):
                        continue
                    compare = api.get(f'repos/{pr_repo}/compare/{sha}...{quote(unquote(tag), safe="")}')
                    if not isinstance(compare, dict) or compare.get('status') not in {'ahead', 'identical', 'behind', 'diverged'}:
                        raise ReadError('release ancestry unavailable')
                    if compare['status'] in {'ahead', 'identical'}:
                        commits = compare.get('commits')
                        if not isinstance(commits, list) or compare.get('total_commits') != len(commits):
                            raise ReadError('release ancestry truncated; revert coverage unknown')
                        if any('revert' in str(c.get('commit', {}).get('message', '')).casefold() for c in commits):
                            raise ReadError('release history contains a revert; reassess delivery')
                        matches.append((release_url, published))
                if not matches:
                    raise ReadError('no declared release contains the merged PR')
                chosen, published = min(matches, key=lambda m: (m[1], m[0]))
                delivered[chosen] = published
                pr_states.append('available')
            if 'unknown' in pr_states:
                states.append('unknown')
            elif 'in_development' in pr_states:
                states.append('in_development')
            elif 'merged_unreleased' in pr_states:
                states.append('merged_unreleased')
            else:
                states.append('available')
        if 'unknown' in states or ('declined' in states and len(set(states)) > 1):
            raise ReadError('delivery is partial or ambiguous across required issues')
        result['state'] = next((s for s in ('in_development', 'accepted', 'merged_unreleased', 'declined') if s in states), 'available')
        if result['state'] == 'available':
            reported = set()
            for entry in source:
                for url in links([entry], 'update'):
                    if url in delivered and utc(entry.get('created_at')) >= delivered[url]:
                        reported.add(url)
            result['update_owed'] = not set(delivered).issubset(reported)
    except (ReadError, ValueError, TypeError, KeyError, AttributeError):
        # Never leak an API exception payload, private target URL or body.
        result['state'] = 'unknown'
        result['gaps'] = ['Delivery evidence missing, incomplete, reverted or not verified public; inspect source.']
    result['evidence'] = sorted(evidence.values(), key=lambda e: e['url'])
    return result


def validate(rows, conversations):
    ids = {r['url'] for r in conversations if r['kind'] == 'discussion'}
    seen = set()
    if not isinstance(rows, list):
        raise ValueError('invalid follow-through projection')
    for r in rows:
        if not isinstance(r, dict) or set(r) != {'discussion', 'state', 'update_owed', 'evidence', 'gaps'}:
            raise ValueError('unknown delivery fields')
        if r['discussion'] not in ids or r['discussion'] in seen or r['state'] not in STATES:
            raise ValueError('invalid delivery identity/state')
        seen.add(r['discussion'])
        if r['update_owed'] is not None and (type(r['update_owed']) is not bool or r['state'] != 'available'):
            raise ValueError('invalid contributor update state')
        if not isinstance(r['gaps'], list) or any(not isinstance(g, str) for g in r['gaps']):
            raise ValueError('invalid delivery gaps')
        if not isinstance(r['evidence'], list):
            raise ValueError('invalid delivery evidence')
        for e in r['evidence']:
            if not isinstance(e, dict) or set(e) != {'url', 'repo', 'kind'}:
                raise ValueError('unknown delivery evidence fields')
            if link(e['url'], e['kind'])[0] != e['repo'] or e['kind'] not in {'issue', 'PR', 'release'}:
                raise ValueError('invalid delivery evidence link')
        if r['state'] == 'available' and ({e['kind'] for e in r['evidence']} != {'issue', 'PR', 'release'} or r['gaps']):
            raise ValueError('available delivery lacks evidence')
