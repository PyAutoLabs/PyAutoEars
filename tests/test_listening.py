"""Coverage and ordering regression cases for the public evidence reader."""
import copy
import json

import pytest

from test_ears import API, CONFIG, STAMP, comments, listing, thread, user
from ears import collect


def node(identity, login='Reporter', stamp=STAMP, **extra):
    return {'id': identity, 'author': {'login': login, '__typename': 'User'},
            'createdAt': stamp, 'deletedAt': None, **extra}


def connection(nodes=(), cursor=None):
    return {'nodes': list(nodes), 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}


class DiscussionAPI(API):
    def __init__(self, graph=None, raw=None, overrides=None):
        super().__init__({listing('example/hub', 'discussions'): [raw or thread(category={'name': 'Help & Questions'})],
                          **(overrides or {})})
        self.graph = graph or {}
        self.graph_calls = []

    def discussion_page(self, repo, number, after=None, comment_id=None):
        self.graph_calls.append((comment_id, after))
        value = self.graph.get((comment_id, after), connection())
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def discussion(api):
    snapshot = collect.collect(api, [], CONFIG)
    collect.validate(snapshot)
    return snapshot['conversations'][0], snapshot['receipts'][0]


def test_all_discussion_comment_and_reply_pages_contribute_to_response_age():
    api = DiscussionAPI({
        (None, None): connection([node('c1', 'Second', '2026-10-02T00:00:00Z')], 'c-page2'),
        (None, 'c-page2'): connection([node('c2', 'Reporter', '2026-10-02T05:00:00Z')]),
        ('c1', None): connection([node('r1', 'SECOND', '2026-10-02T01:00:00Z')], 'r-page2'),
        ('c1', 'r-page2'): connection([node('r2', 'Reporter', '2026-10-02T02:00:00Z')]),
    })
    row, receipt = discussion(api)
    assert row['coverage'] == receipt['status'] == 'complete'
    assert row['awaiting_response'] is True
    assert row['waiting_since'] == '2026-10-02T02:00:00+00:00'
    assert ('c1', 'r-page2') in api.graph_calls and ('c2', None) in api.graph_calls
    assert comments('example/hub', 'discussions') not in api.calls


def test_nested_maintainer_reply_settles_response():
    row, _ = discussion(DiscussionAPI({
        (None, None): connection([node('c1', 'Reporter', '2026-10-02T00:00:00Z')]),
        ('c1', None): connection([node('r1', 'sEcOnD')]),
    }))
    assert row['awaiting_response'] is False and row['waiting_since'] is None


@pytest.mark.parametrize('failure', [
    collect.ReadError('rate limit'), {'nodes': []}, connection([None]),
    connection([node('r1')], 'repeat'),
])
def test_reply_failure_malformed_or_cap_stays_unknown(failure):
    api = DiscussionAPI({(None, None): connection([node('c1')]),
                         ('c1', None): failure, ('c1', 'repeat'): failure})
    row, receipt = discussion(api)
    assert row['coverage'] == receipt['status'] == 'partial'
    assert row['awaiting_response'] is None and row['gaps']


@pytest.mark.parametrize('event', [node('c1', author=None), node('c1', deletedAt=STAMP),
                                   node('c1', stamp=None), node('c1', author={'login': 42})])
def test_deleted_author_or_unknown_time_is_never_checked_clear(event):
    row, receipt = discussion(DiscussionAPI({(None, None): connection([event])}))
    assert row['awaiting_response'] is None
    assert row['coverage'] == receipt['status'] == 'partial'


def test_rest_only_fallback_is_explicitly_partial():
    row, _ = discussion(API({listing('example/hub', 'discussions'): [thread()],
                           comments('example/hub', 'discussions'): [{'user': user('Maintainer'), 'created_at': STAMP}]}))
    assert row['awaiting_response'] is None
    assert 'Discussion GraphQL adapter unavailable' in row['gaps']


@pytest.mark.parametrize('category,answer', [('Ideas & Proposals', STAMP), ('Announcements', None), ('Show and tell', None)])
def test_accepted_proposal_or_broadcast_does_not_claim_delivery(category, answer):
    row, receipt = discussion(DiscussionAPI(raw=thread(category={'name': category}, answer_chosen_at=answer)))
    assert row['awaiting_response'] is False
    assert row['coverage'] == receipt['status'] == 'complete'
    assert 'delivered' not in row and 'delivery_state' not in row


def test_empty_success_is_distinct_from_inaccessible_connection():
    complete, _ = discussion(DiscussionAPI())
    partial, _ = discussion(DiscussionAPI({(None, None): collect.ReadError('not accessible')}))
    assert complete['awaiting_response'] is True and complete['coverage'] == 'complete'
    assert partial['awaiting_response'] is None and partial['coverage'] == 'partial'


def test_unknown_issue_author_remains_visible():
    snapshot = collect.collect(API({listing(): [thread(user=None)]}), ['example/lib'], CONFIG)
    assert len(snapshot['conversations']) == 1
    assert snapshot['conversations'][0]['awaiting_response'] is None


def test_pr_review_replies_paginate_and_deleted_actor_degrades():
    api = API({listing(): [thread(pull_request={})],
               comments(kind='pulls'): [{'user': user('Reporter'), 'created_at': STAMP}] * 100,
               comments(kind='pulls', page=2): [{'user': user('Second'), 'created_at': '2026-10-04T00:00:00Z', 'in_reply_to_id': 1}]})
    row = collect.collect(api, ['example/lib'], CONFIG)['conversations'][0]
    assert row['awaiting_response'] is False
    api.overrides[comments(kind='pulls', page=2)][0]['user'] = None
    row = collect.collect(api, ['example/lib'], CONFIG)['conversations'][0]
    assert row['awaiting_response'] is None and row['coverage'] == 'partial'


def test_graphql_transport_only_fixed_queries_and_no_mutations(monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append((args, json.loads(kw['input'])))
        return type('Result', (), {'returncode': 0, 'stdout': json.dumps({'data': {'repository': {'discussion': {'comments': connection()}}}})})()
    monkeypatch.setattr(collect.subprocess, 'run', run)
    assert collect.GitHub().discussion_page('example/hub', 1) == connection()
    args, payload = calls[0]
    assert args == ['gh', 'api', 'graphql', '--input', '-']
    assert payload['query'] == collect.DISCUSSION_COMMENTS
    assert 'body' in payload['query'] and 'mutation' not in payload['query']
    assert payload['variables'] == {'owner': 'example', 'name': 'hub', 'number': 1}


@pytest.mark.parametrize('response', [{'data': {'repository': {'discussion': {'comments': connection()}}}, 'errors': [{'message': 'SECRET'}]}, {'data': {'repository': None}}, []])
def test_graphql_errors_never_leak_or_count_as_empty_success(monkeypatch, response):
    monkeypatch.setattr(collect.subprocess, 'run', lambda *a, **k: type('Result', (), {'returncode': 0, 'stdout': json.dumps(response)})())
    with pytest.raises(collect.ReadError) as exc:
        collect.GitHub().discussion_page('example/hub', 1)
    assert 'SECRET' not in str(exc.value)
