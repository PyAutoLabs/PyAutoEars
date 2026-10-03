"""Authoritative links, partial delivery, privacy and contributor updates."""
import copy
import json

import pytest

from test_ears import API, CONFIG, BRAIN, STAMP, comments, thread, user
from test_listening import DiscussionAPI, connection, node
from ears import board, collect, followthrough as f

D = 'https://github.com/example/hub/discussions/1'
I = 'https://github.com/example/lib/issues/2'
P = 'https://github.com/example/lib/pull/3'
R = 'https://github.com/example/lib/releases/tag/v1'
SHA = 'a' * 40


def source(body, stamp=STAMP, who='Maintainer'):
    return {'body': body, 'user': user(who), 'created_at': stamp}


def api_fixture():
    return API({
        'repos/example/lib/issues/2': thread(2, login='Maintainer', state='closed', state_reason='completed',
                                           body=f'Delivery-PR: {P}\nDelivery-release: {R}'),
        'repos/example/lib/pulls/3': {'state': 'closed', 'merged': True, 'merge_commit_sha': SHA,
                                    'merged_at': '2026-10-01T12:00:00Z'},
        'repos/example/lib/releases/tags/v1': {'draft': False, 'prerelease': False, 'published_at': '2026-10-02T12:00:00Z'},
        f'repos/example/lib/compare/{SHA}...v1': {'status': 'ahead', 'commits': [], 'total_commits': 0},
    })


def derive(api=None, entries=None, pending=set(), complete=True):
    return f.derive(api or api_fixture(), D, entries or [source('Delivery-issue: ' + I)], CONFIG, complete, pending)


def test_available_requires_release_and_update_after_publication():
    assert derive()['state'] == 'available' and derive()['update_owed'] is True
    entries = [source('Delivery-issue: ' + I), source('Delivery-update: ' + R)]
    assert derive(entries=entries)['update_owed'] is False
    entries[-1]['created_at'] = '2026-10-01T00:00:00Z'
    assert derive(entries=entries)['update_owed'] is True
    entries[-1] = source('We mentioned ' + R)
    assert derive(entries=entries)['update_owed'] is True


def test_pending_release_is_authoritative_and_missing_mind_is_unknown():
    assert derive(pending={P})['state'] == 'merged_unreleased'
    assert derive(pending=None)['state'] == 'unknown'
    a = api_fixture()
    a.overrides['repos/example/lib/issues/2']['body'] = 'Delivery-PR: ' + P
    assert derive(a)['state'] == 'merged_unreleased'


@pytest.mark.parametrize('change', ['failed_release', 'draft', 'prerelease', 'diverged', 'truncated', 'revert', 'reopened', 'closed_pr', 'incomplete_comments'])
def test_incomplete_and_reverted_evidence_never_claims_available(change):
    a = api_fixture()
    release = a.overrides['repos/example/lib/releases/tags/v1']
    compare = a.overrides[f'repos/example/lib/compare/{SHA}...v1']
    if change == 'failed_release': a.overrides['repos/example/lib/releases/tags/v1'] = collect.ReadError('SECRET')
    elif change in {'draft', 'prerelease'}: release[change] = True
    elif change == 'diverged': compare['status'] = 'diverged'
    elif change == 'truncated': compare['total_commits'] = 2
    elif change == 'revert':
        compare.update(commits=[{'commit': {'message': 'Revert earlier fix'}}], total_commits=1)
    elif change == 'reopened': a.overrides['repos/example/lib/issues/2']['state'] = 'open'
    elif change == 'closed_pr': a.overrides['repos/example/lib/pulls/3']['merged'] = False
    else: a.overrides[comments(n=2)] = collect.ReadError('SECRET')
    result = derive(a)
    assert result['state'] == 'unknown' and result['update_owed'] is None
    assert 'SECRET' not in json.dumps(result)


def test_multiple_prs_must_all_be_delivered():
    a = api_fixture()
    a.overrides['repos/example/lib/issues/2']['body'] += '\nDelivery-PR: https://github.com/example/lib/pull/4'
    a.overrides['repos/example/lib/pulls/4'] = {'state': 'open', 'merged': False}
    assert derive(a)['state'] == 'in_development'
    a.overrides['repos/example/lib/pulls/4'] = dict(a.overrides['repos/example/lib/pulls/3'])
    assert derive(a)['state'] == 'available'


def test_accepted_declined_absent_links_and_explicit_revert():
    a = api_fixture()
    issue = a.overrides['repos/example/lib/issues/2']
    issue.update(state='open', body='No linked PR yet')
    assert derive(a)['state'] == 'accepted'
    issue.update(state='closed', state_reason='not_planned')
    assert derive(a)['state'] == 'declined'
    assert derive(entries=[source('Mention ' + I)])['state'] == 'unknown'
    issue['body'] = 'Delivery-revert: ' + P
    assert derive(a)['state'] == 'unknown'


def test_untrusted_actor_and_private_link_not_followed_or_exported():
    a = api_fixture()
    assert derive(a, entries=[source('Delivery-issue: ' + I, who='Reporter')])['state'] == 'unknown'
    assert not a.calls
    a.overrides['repos/example/lib'] = {'private': True}
    result = derive(a)
    assert not result['evidence'] and I not in json.dumps(result)
    assert 'repos/example/lib/issues/2' not in a.calls
    assert derive(complete=False)['state'] == 'unknown'


def delivery_snapshot():
    a = api_fixture()
    raw = thread(1, state='closed', answer_chosen_at=STAMP, category={'name': 'Ideas & Proposals'})
    api = DiscussionAPI({
        (None, None): connection([node('c1', body='PRIVATE RAW TEXT')]),
        ('c1', None): connection([node('r1', 'Maintainer', stamp='2026-10-03T13:00:00Z', body='Delivery-issue: ' + I)]),
    }, overrides={**a.overrides,
                  'repos/example/hub/discussions?state=open&per_page=100&page=1': [],
                  'repos/example/hub/discussions?state=closed&per_page=100&page=1': [raw]})
    snap = collect.collect(api, [], CONFIG, set())
    return snap


def test_closed_discussion_nested_links_live_collection_no_body_export():
    snap = delivery_snapshot()
    collect.validate(snap)
    assert snap['follow_through'][0]['state'] == 'available'
    assert snap['conversations'][0]['awaiting_response'] is False
    assert 'PRIVATE RAW TEXT' not in json.dumps(snap)
    surfaces = board.render(snap, CONFIG, BRAIN, rendered_at=snap['generated'])
    assert 'contributor update owed' in surfaces['index.html']
    assert 'do not post' in surfaces['index.html']
    assert any(i['text'] == 'Contributor update owed' for i in json.loads(surfaces['state.json'])['items'])
    old = copy.deepcopy(snap)
    old.pop('follow_through')
    collect.validate(old)
    assert 'No delivery evidence' in board.render(old, CONFIG, BRAIN)['index.html']
    snap['follow_through'][0]['evidence'][0]['url'] = 'javascript:alert(1)'
    with pytest.raises(ValueError): collect.validate(snap)


def test_pending_release_reads_real_keys_only(tmp_path):
    (tmp_path / 'complete').mkdir()
    (tmp_path / 'active.md').write_text('- pending-release: library@' + P)
    (tmp_path / 'complete' / 'record.md').write_text('Quoted mention ' + R)
    assert f.pending_releases(tmp_path) == {P}
    with pytest.raises(ValueError): f.pending_releases(tmp_path / 'missing')
