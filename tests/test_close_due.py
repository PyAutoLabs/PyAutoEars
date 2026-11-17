"""Threads waiting on their contributor for 21 days are due for the close message."""
import copy

import pytest

from test_ears import API, CONFIG, STAMP, comments, listing, thread, user
from test_listening import DiscussionAPI, connection, discussion, node
from ears import board, collect
from test_ears import BRAIN

EXACT = '2026-09-12T12:00:00Z'      # exactly 21 days before STAMP
INSIDE = '2026-09-12T12:00:01Z'     # one second short of 21 days
EARLY = '2026-09-01T00:00:00Z'


@pytest.fixture(autouse=True)
def fixed_collection_time(monkeypatch):
    monkeypatch.setattr(collect, 'now', lambda: STAMP)


def issue_row(activity, **raw):
    api = API({listing(): [thread(created_at='2026-08-30T00:00:00Z', **raw)], comments(): activity})
    snapshot = collect.collect(api, ['example/lib'], CONFIG)
    collect.validate(snapshot)
    return snapshot['conversations'][0], snapshot


def said(login, stamp, bot=False):
    return {'user': {'login': login, 'type': 'Bot' if bot else 'User'}, 'created_at': stamp}


@pytest.mark.parametrize('stamp, due', [(EXACT, True), (INSIDE, False)])
def test_boundary_at_exactly_21_days_is_due(stamp, due):
    row, _ = issue_row([said('Reporter', EARLY), said('Maintainer', stamp)])
    assert row['awaiting_response'] is False
    assert row['awaiting_contributor_since'] == collect.utc(stamp).isoformat()
    assert row['close_due'] is due


def test_bot_comment_after_ours_does_not_reset_the_clock():
    row, _ = issue_row([said('Reporter', EARLY), said('Maintainer', EXACT),
                        said('stale[bot]', '2026-10-01T00:00:00Z', bot=True)])
    assert row['close_due'] is True
    assert row['awaiting_contributor_since'] == '2026-09-12T12:00:00+00:00'


def test_external_reply_after_ours_means_we_owe_the_reply():
    row, _ = issue_row([said('Maintainer', EARLY), said('Reporter', EXACT)])
    assert row['awaiting_response'] is True
    assert row['awaiting_contributor_since'] is None and row['close_due'] is False


def test_thread_with_no_comments_is_not_awaiting_the_contributor():
    row, _ = issue_row([])
    assert row['awaiting_contributor_since'] is None and row['close_due'] is False


def test_incomplete_coverage_gives_null():
    row, snapshot = issue_row([said('Reporter', EARLY), {'user': None, 'created_at': EXACT},
                               said('Maintainer', EXACT)])
    assert row['coverage'] == 'partial'
    assert row['awaiting_contributor_since'] is None and row['close_due'] is None


def test_nested_maintainer_reply_on_open_discussion_is_due():
    raw = thread(category={'name': 'Help & Questions'}, created_at='2026-08-30T00:00:00Z')
    row, _ = discussion(DiscussionAPI({
        (None, None): connection([node('c1', 'Reporter', EARLY)]),
        ('c1', None): connection([node('r1', 'Second', EXACT)]),
    }, raw=raw))
    assert row['kind'] == 'discussion' and row['close_due'] is True


@pytest.mark.parametrize('variant', ['answered', 'broadcast', 'locked', 'own_thread'])
def test_settled_or_ineligible_discussions_carry_no_close_due(variant):
    raw = thread(category={'name': 'Help & Questions'}, created_at='2026-08-30T00:00:00Z')
    if variant == 'answered':
        raw['answer_chosen_at'] = EARLY
    if variant == 'broadcast':
        raw['category'] = {'name': 'Announcements'}
    if variant == 'locked':
        raw['locked'] = True
    if variant == 'own_thread':
        raw['user'] = user('Maintainer')
    row, _ = discussion(DiscussionAPI({(None, None): connection([node('c1', 'Maintainer', EXACT)])}, raw=raw))
    assert 'close_due' not in row and 'awaiting_contributor_since' not in row


def test_pull_requests_carry_no_close_due():
    row, _ = issue_row([said('Maintainer', EXACT)], pull_request={})
    assert row['kind'] == 'pr' and 'close_due' not in row


@pytest.mark.parametrize('mutation', [
    lambda r: r.update(close_due=False),                                 # disagrees with the clock
    lambda r: r.update(awaiting_contributor_since=INSIDE),               # too recent to be due
    lambda r: r.update(closed=True),                                     # settled thread
    lambda r: r.update(close_due=None),                                  # null with a timestamp
    lambda r: r.update(close_due='yes'),
    lambda r: r.update(coverage='partial', awaiting_response=None),
    lambda r: r.pop('awaiting_contributor_since'),
    lambda r: r.update(awaiting_response=True, waiting_since=EXACT),
])
def test_validation_rejects_inconsistent_close_due(mutation):
    _, snapshot = issue_row([said('Reporter', EARLY), said('Maintainer', EXACT)])
    bad = copy.deepcopy(snapshot)
    mutation(bad['conversations'][0])
    with pytest.raises(ValueError):
        collect.validate(bad)


def test_old_snapshots_without_the_fields_remain_valid():
    _, snapshot = issue_row([said('Reporter', EARLY), said('Maintainer', EXACT)])
    for key in ('close_due', 'awaiting_contributor_since'):
        snapshot['conversations'][0].pop(key)
    collect.validate(snapshot)


def test_board_shows_a_quiet_close_due_label_and_valid_state():
    import json
    _, snapshot = issue_row([said('Reporter', EARLY), said('Maintainer', EXACT)])
    result = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    assert 'Close due' in result['index.html']
    state = json.loads(result['state.json'])
    assert not board.presentation(BRAIN)[1].validate_state(state)
