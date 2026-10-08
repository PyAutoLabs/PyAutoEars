"""New requests must be visible without requiring a contributor to reopen."""
import copy
import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from test_ears import API, CONFIG, BRAIN, STAMP, thread, user, comments
from test_listening import DiscussionAPI, discussion, node, connection
from ears import collect, board

CLOSED = '2026-10-02T00:00:00Z'
LATER = '2026-10-03T00:00:00Z'


@pytest.fixture(autouse=True)
def fixed_collection_time(monkeypatch):
    monkeypatch.setattr(collect, 'now', lambda: STAMP)


def settled(**kwargs):
    return thread(state='closed', closed_at=CLOSED, answer_chosen_at=CLOSED,
                  category={'name': 'Ideas & Proposals'}, **kwargs)


@pytest.mark.parametrize('body', ['Could you add analytic streamed components?', 'Thanks!'])
def test_new_nested_reply_on_closed_answered_thread_is_review_candidate(body):
    api = DiscussionAPI({(None, None): connection([node('answer', 'Maintainer', CLOSED)]),
                         ('answer', None): connection([node('reply', stamp=LATER, databaseId=18676930, body=body)])}, raw=settled())
    row, receipt = discussion(api)
    assert row['closed'] and row['answered']
    assert row['awaiting_response'] is True and receipt['status'] == 'complete'
    assert row['follow_up'] == {'review_needed': True, 'since': '2026-10-03T00:00:00+00:00',
                                'url': 'https://github.com/example/hub/discussions/1#discussioncomment-18676930'}
    assert body not in json.dumps(row)  # judgment and source bodies stay out of snapshots


@pytest.mark.parametrize('state', ['open', 'closed'])
def test_pre_settlement_comments_do_not_reactivate_old_requests(state):
    raw = settled(); raw['state'] = state
    row, _ = discussion(DiscussionAPI({(None, None): connection([node('old', stamp='2026-10-01T15:00:00Z')])}, raw=raw))
    assert row['follow_up']['review_needed'] is False
    assert row['awaiting_response'] is False


def test_answered_open_thread_and_later_maintainer_response_then_renewed_followup():
    raw = settled(); raw['state'] = 'open'
    nodes = [node('request', stamp=LATER), node('handled', 'Maintainer', STAMP)]
    api = DiscussionAPI({(None, None): connection(nodes)}, raw=raw)
    assert discussion(api)[0]['follow_up']['review_needed'] is False
    api.graph[(None, None)]['nodes'].append(node('another', stamp='2026-10-04T00:00:00Z'))
    row, _ = discussion(api)
    assert row['follow_up']['review_needed'] is True
    assert row['waiting_since'] == '2026-10-04T00:00:00+00:00'


@pytest.mark.parametrize('failure', ['timestamp', 'settlement', 'pagination', 'author'])
def test_incomplete_evidence_is_unknown_even_on_closed_answered_threads(failure):
    raw = settled()
    activity = node('new', stamp=LATER)
    graph = {(None, None): connection([activity])}
    if failure == 'timestamp': activity['createdAt'] = None
    if failure == 'author': activity['author'] = None
    if failure == 'settlement': raw.pop('closed_at')
    if failure == 'pagination': graph[('new', None)] = collect.ReadError('failed')
    row, receipt = discussion(DiscussionAPI(graph, raw=raw))
    assert row['follow_up']['review_needed'] is None
    assert row['awaiting_response'] is None
    assert row['coverage'] == receipt['status'] == 'partial'


def test_graphql_supplies_missing_rest_closure_time():
    api = DiscussionAPI({(None, None): connection([node('new', stamp=LATER)])}, raw=settled())
    api.overrides[next(k for k in api.overrides if 'state=open' in k)][0].pop('closed_at')
    api.discussion_state = lambda repo, n: {'closed': True, 'closedAt': CLOSED, 'answerChosenAt': CLOSED}
    assert discussion(api)[0]['follow_up']['review_needed'] is True
    api.discussion_state = lambda repo, n: {'closed': False, 'closedAt': None, 'answerChosenAt': CLOSED}
    assert discussion(api)[0]['follow_up']['review_needed'] is None


def closed_listing(repo='example/lib', page=1):
    return f'repos/{repo}/issues?state=closed&sort=updated&direction=desc&per_page=100&page={page}'


@pytest.mark.parametrize('author', ['Reporter', 'Maintainer'])
def test_closed_issue_comments_are_collected_independently_of_issue_author(author):
    api = API({closed_listing(): [thread(login=author, state='closed', closed_at=CLOSED),
                                 thread(2, pull_request={}, state='closed')],
               comments(): [{'id': 42, 'user': user('Reporter'), 'created_at': LATER}]})
    snapshot = collect.collect(api, ['example/lib'], CONFIG)
    collect.validate(snapshot)
    assert len(snapshot['conversations']) == 1
    assert snapshot['conversations'][0]['follow_up']['url'].endswith('#issuecomment-42')
    assert not any('/pulls/' in c for c in api.calls)


def test_quiet_and_bot_only_closed_issues_do_not_crowd_queue():
    api = API({closed_listing(): [thread(state='closed', closed_at=CLOSED)],
               comments(): [{'user': {'login': 'robot[bot]', 'type': 'Bot'}, 'created_at': LATER}]})
    assert collect.collect(api, ['example/lib'], CONFIG)['conversations'] == []


def test_truncated_closed_issue_scan_retains_candidates_and_reports_gap():
    api = API({closed_listing(): [thread(n, state='closed', closed_at=CLOSED) for n in range(1, 101)],
               closed_listing(page=2): collect.ReadError('read failed'),
               comments(): [{'user': user('Reporter'), 'created_at': LATER}]})
    s = collect.collect(api, ['example/lib'], CONFIG)
    assert len(s['conversations']) == 1
    receipt = next(r for r in s['receipts'] if r['repo'] == 'example/lib')
    assert receipt['status'] == 'partial' and 'closed issues' in receipt['gaps'][0]


def candidate_snapshot():
    api = DiscussionAPI({(None, None): connection([node('new', stamp=LATER, databaseId=18676930)])}, raw=settled())
    with patch('ears.collect.now', return_value=STAMP):
        s = collect.collect(api, [], CONFIG)
    return s


def historical_snapshot(kind='issue', latest='2020-02-02T00:00:00Z', extra=()):
    raw = thread(state='closed', created_at='2020-01-01T00:00:00Z',
                 closed_at='2020-02-01T00:00:00Z', updated_at=STAMP)
    if kind != 'issue':
        raw.update(answer_chosen_at=raw['closed_at'], category={'name': 'Help & Questions'})
        if kind == 'answered':
            raw['state'] = 'open'
        api = DiscussionAPI({(None, None): connection([
            node('old', stamp='2020-02-02T00:00:00Z'),
            node('latest', stamp=latest), *extra])}, raw=raw)
    else:
        api = API({closed_listing(): [raw], comments(): [
            {'id': 41, 'user': user('Reporter'), 'created_at': '2020-02-02T00:00:00Z'},
            {'id': 42, 'user': user('Reporter'), 'created_at': latest}, *extra]})
    with patch('ears.collect.now', return_value=STAMP):
        snapshot = collect.collect(api, ['example/lib'] if kind == 'issue' else [], CONFIG)
    collect.validate(snapshot)
    return snapshot


@pytest.mark.parametrize('kind', ['issue', 'discussion', 'answered'])
@pytest.mark.parametrize('seconds_old,historical', [(30 * 86400 + 1, True), (30 * 86400, False), (29 * 86400, False)])
def test_cutoff_uses_latest_external_followup_not_oldest_pending_or_thread_update(kind, seconds_old, historical):
    latest = (collect.utc(STAMP) - timedelta(seconds=seconds_old)).isoformat()
    s = historical_snapshot(kind, latest)
    row = s['conversations'][0]
    assert row['awaiting_response'] is not historical
    assert row['follow_up']['review_needed'] is not historical
    if historical:
        assert row['historical_follow_up_at'] == latest
        assert row['waiting_since'] is None
        assert row['follow_up'] == {'review_needed': False, 'since': None, 'url': None}
    else:
        assert 'historical_follow_up_at' not in row
        assert row['waiting_since'] == '2020-02-02T00:00:00+00:00'


def test_historical_followup_stays_in_activity_and_out_of_feed_attention():
    s = historical_snapshot()
    result = board.render(s, CONFIG, BRAIN, STAMP)
    attention, activity = result['index.html'].split('id="activity"', 1)
    assert '<details class="topic">' not in attention
    assert 'Historical follow-up' in activity
    assert 'Last external follow-up:' in activity
    assert 'Activity needs review' not in activity
    assert 'Historical follow-up' in result['dashboard.md']
    state = json.loads(result['state.json'])
    assert state['status'] == 'green'
    assert not state['items']
    adapter = board.load_module(BRAIN / 'agents/conductors/community/_ears_feed.py', 'ears_window_adapter')
    adapted = adapter.adapt(s, state, CONFIG['self_logins'], 'example', CONFIG['hub'], current=collect.utc(STAMP))
    assert adapted['counts']['awaiting_response'] == 0


def test_new_reply_reactivates_history_and_bots_do_not():
    bot = {'user': {'login': 'robot[bot]', 'type': 'Bot'}, 'created_at': STAMP}
    assert historical_snapshot(extra=[bot])['conversations'][0]['historical_follow_up_at']
    fresh = {'user': user('AnotherReporter'), 'created_at': STAMP}
    row = historical_snapshot(extra=[fresh])['conversations'][0]
    assert row['awaiting_response'] is True and 'historical_follow_up_at' not in row
    maintainer = {'user': user('Maintainer'), 'created_at': STAMP}
    assert historical_snapshot(extra=[maintainer])['conversations'] == []


def test_old_open_issue_is_not_aged_out():
    from test_ears import listing
    s = collect.collect(API({listing(): [thread(created_at='2020-01-01T00:00:00Z')]}), ['example/lib'], CONFIG)
    assert s['conversations'][0]['awaiting_response'] is True
    assert 'historical_follow_up_at' not in s['conversations'][0]


@pytest.mark.parametrize('extra', [
    {'user': user('Reporter'), 'created_at': None},
    {'user': None, 'created_at': STAMP},
])
def test_old_incomplete_activity_cannot_be_classified_as_historical(extra):
    row = historical_snapshot(extra=[extra])['conversations'][0]
    assert row['awaiting_response'] is None and row['coverage'] == 'partial'
    assert 'historical_follow_up_at' not in row


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(historical_follow_up_at=STAMP),
    lambda r: r.update(historical_follow_up_at=None),
    lambda r: r.update(coverage='partial'),
    lambda r: r.update(waiting_since=LATER),
    lambda r: r.pop('follow_up'),
    lambda r: r.update(closed=False),
])
def test_historical_metadata_must_have_complete_expired_settled_evidence(mutation):
    s = historical_snapshot(); mutation(s['conversations'][0])
    with pytest.raises(ValueError):
        collect.validate(s)


def test_board_keeps_thread_status_and_permission_aware_review_visible():
    s = candidate_snapshot()
    rendered = board.render(s, CONFIG, BRAIN, STAMP)
    assert 'Follow-up needs review' in rendered['index.html']
    assert 'Closed · Answered' in rendered['index.html']
    assert '#discussioncomment-18676930' in rendered['index.html']
    assert 'Contributors may lack' in rendered['index.html']
    assert 'permission' in json.loads(rendered['state.json'])['items'][0]['prompt']
    assert json.loads(rendered['state.json'])['status'] == 'yellow'
    assert json.loads(board.render(s, CONFIG, BRAIN, '2026-10-05T00:00:00Z')['state.json'])['status'] == 'stale'


@pytest.mark.parametrize('mutation', [
    lambda f: f.update(url='javascript:alert(1)'),
    lambda f: f.update(url='https://github.com/other/repo/issues/1'),
    lambda f: f.update(review_needed='yes'),
    lambda f: f.update(body='must never export'),
    lambda f: f.update(since=None),
])
def test_followup_extension_rejects_unsafe_or_inconsistent_evidence(mutation):
    s = candidate_snapshot(); mutation(s['conversations'][0]['follow_up'])
    with pytest.raises(ValueError): collect.validate(s)


@pytest.mark.parametrize('metadata', [dict(comments=0), dict(comments=5, updated_at=CLOSED)])
def test_quiet_closed_history_does_not_need_per_issue_comment_requests(metadata):
    api = API({closed_listing(): [thread(state='closed', closed_at=CLOSED, **metadata)]})
    assert collect.collect(api, ['example/lib'], CONFIG)['conversations'] == []
    assert comments() not in api.calls


def test_discussion_settlement_transport_is_fixed_read_only_query(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, json.loads(kwargs['input'])))
        return type('Result', (), {'returncode': 0, 'stdout': json.dumps({
            'data': {'repository': {'discussion': {'closed': True, 'closedAt': CLOSED, 'answerChosenAt': CLOSED}}}})})()
    monkeypatch.setattr(collect.subprocess, 'run', run)
    assert collect.GitHub().discussion_state('example/hub', 13)['closedAt'] == CLOSED
    assert calls[0][1]['query'] == collect.DISCUSSION_STATE
    assert 'mutation' not in calls[0][1]['query']
