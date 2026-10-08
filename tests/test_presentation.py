"""User-visible distinctions and safe progressive enhancement."""
import json

import pytest

from test_ears import BRAIN, CONFIG, STAMP, fixture
from test_followthrough import I, delivery_snapshot
from ears import board
from ears.presentation import progress, recorded_plans, waiting_label


def test_authors_tables_and_details_do_not_execute_source_text():
    snapshot = fixture()
    row = snapshot['conversations'][0]
    row['author'] = '<img src=x onerror=alert(1)>'
    page = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)['index.html']
    assert '@&lt;img' in page and '<img src=x' not in page
    assert '<table class="community">' in page
    assert '<details class="topic">' in page
    assert 'aria-label="Copy triage prompt"' in page
    assert 'Response states are heuristics' not in page
    assert page.index('id="activity"') < page.index('id="coverage"')
    assert 'id="follow-through"' not in page
    assert 'id="unknown"' not in page
    assert 'Open Community Hub ↗' in page


def test_attention_with_unknown_coverage_appears_once():
    snapshot = fixture()
    snapshot['conversations'][0].update(coverage='partial', review_requested=True)
    result = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    assert result['index.html'].count('<details class="topic">') == 1
    assert '>Unknown</span>' in result['index.html']
    assert any(item['state'] == 'unknown' for item in json.loads(result['state.json'])['items'])


def test_activity_includes_author_and_answer_is_not_delivery():
    snapshot = delivery_snapshot()
    snapshot['follow_through'][0].update(state='unknown', update_owed=None, evidence=[])
    page = board.render(snapshot, CONFIG, BRAIN, rendered_at=snapshot['generated'])['index.html']
    activity = page.split('id="activity"')[1].split('id="coverage"')[0]
    assert '@Reporter' in activity
    assert '>Released<' not in activity


@pytest.mark.parametrize('state,label', [('accepted', 'Issue linked'), ('in_development', 'PR open'),
    ('merged_unreleased', 'Merged · unreleased'), ('available', 'Released'), ('declined', 'Declined')])
def test_progress_uses_delivery_states_and_expires(state, label):
    snapshot = delivery_snapshot()
    row = snapshot['conversations'][0]
    delivery = snapshot['follow_through'][0]
    delivery['state'] = state
    assert progress(row, delivery, False, ())[0] == label
    assert progress(row, delivery, True, ())[0] == 'Refresh needed'
    row['coverage'] = 'partial'
    assert progress(row, delivery, False, ())[0] == 'Unknown'


def test_plan_hints_require_explicit_issued_record_and_nonempty_plan(tmp_path):
    (tmp_path / 'active').mkdir()
    (tmp_path / 'draft').mkdir()
    valid = '# Task\nIssue: ' + I + '\n\n## Plan\nImplement the fix.\n'
    (tmp_path / 'draft' / 'draft.md').write_text(valid)
    p = tmp_path / 'active' / 'task.md'
    for invalid in (valid.replace('Issue:', 'Mention:'), valid.replace('Implement the fix.', ''),
                    '# Task\n```text\n' + valid + '```\n',
                    valid.replace('## Plan', '## Request')):
        p.write_text(invalid)
        assert recorded_plans(tmp_path) == set()
    p.write_text(valid)
    assert recorded_plans(tmp_path) == {I}
    snapshot = delivery_snapshot()
    delivery = snapshot['follow_through'][0]
    delivery.update(state='accepted', update_owed=None)
    assert progress(snapshot['conversations'][0], delivery, False, {I})[0] == 'Plan recorded'
    delivery['state'] = 'in_development'
    assert progress(snapshot['conversations'][0], delivery, False, {I})[0] == 'PR open'


def test_old_snapshots_still_render_and_plan_hints_do_not_change_feed():
    snapshot = fixture()
    snapshot.pop('follow_through', None)
    for row in snapshot['conversations']:
        row.pop('created_at', None)
        row.pop('updated_at', None)
    baseline = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    assert '<td class="conversation-date">Unavailable</td>' in baseline['index.html']
    with_plan = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP, plans={snapshot['conversations'][0]['url']})
    assert '>Plan recorded<' in with_plan['index.html']
    assert baseline['state.json'] == with_plan['state.json']
    assert baseline['badge.json'] == with_plan['badge.json']


def test_conversation_dates_in_both_tables_do_not_change_feed_or_waiting_age():
    snapshot = fixture()
    from copy import deepcopy
    activity = deepcopy(snapshot['conversations'][0])
    activity.update(id='example/lib/issues/2', number=2,
                    url='https://github.com/example/lib/issues/2',
                    awaiting_response=False, waiting_since=None)
    snapshot['conversations'].append(activity)
    baseline = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    snapshot['conversations'][0]['updated_at'] = STAMP
    result = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    page = result['index.html']
    assert page.count('<th scope="col">Updated</th>') == 2
    assert '<time datetime="2026-10-03T12:00:00Z">03 Oct 2026</time></td>' in page
    assert '01 Oct 2026</time> (created)' in page
    assert '03 Oct 2026' in result['dashboard.md']
    assert '01 Oct 2026 (created)' in result['dashboard.md']
    assert '2d waiting' in page
    assert result['state.json'] == baseline['state.json']
    assert 'topic-meta' not in page
    assert 'Open issue ↗' not in page
    assert 'Recurring feedback' not in page
    assert page.count('aria-label="Open conversation on GitHub"') == 2


def test_waiting_age_uses_observation_not_render_time():
    row = fixture()['conversations'][0]
    assert waiting_label(row, STAMP) == '2d waiting'
    row['waiting_since'] = '2026-10-04T12:00:00Z'
    assert waiting_label(row, STAMP) == 'Time unknown'


def test_cli_reads_mind_plan_hints_when_rendering_snapshot(tmp_path):
    from ears.cli import main
    snapshot = fixture()
    # A fresh envelope is required for current progress claims.
    from ears.collect import now
    snapshot['generated'] = now()
    source = tmp_path / 'snapshot.json'
    source.write_text(json.dumps(snapshot))
    mind = tmp_path / 'mind'
    (mind / 'active').mkdir(parents=True)
    (mind / 'active' / 'task.md').write_text('# Task\nIssue: ' + snapshot['conversations'][0]['url'] + '\n\n## Plan\nFix the issue.\n')
    output = tmp_path / 'site'
    assert main(['board', '--snapshot', str(source), '--brain', str(BRAIN), '--mind', str(mind), '--output', str(output)]) == 0
    assert '>Plan recorded<' in (output / 'index.html').read_text()


def test_shared_checkin_keeps_public_destinations_and_inert_payload():
    import html
    import re
    from ears.presentation import CHECKIN

    snapshot = fixture()
    snapshot['receipts'].append({'repo': 'private/unknown', 'checked_at': STAMP,
                                 'status': 'unavailable', 'public_verified': False, 'gaps': []})
    page = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)['index.html']
    panel = re.search(r'<section class="orchestration-panel".*?</section>', page, re.S)[0]
    assert 'Open Community Hub ↗' in panel
    assert 'https://github.com/' + CONFIG['repo'] in panel
    assert 'https://github.com/private/unknown' not in panel
    preview = html.unescape(re.search(r'data-orchestration-prompt readonly rows="8">(.*?)</textarea>', panel, re.S)[1])
    assert preview.startswith(CHECKIN + "\n\nWork on GitHub:\n")
    snapshot['receipts'][-1]['public_verified'] = True
    page = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)['index.html']
    panel = re.search(r'<section class="orchestration-panel".*?</section>', page, re.S)[0]
    assert 'https://github.com/private/unknown' not in panel
    assert len(re.findall(r'<a ', panel)) == 3
    assert f'https://github.com/{CONFIG["repo"]}/actions/workflows/pages.yml' in panel
    assert 'Last updated unavailable' in panel
    assert 'orchestrationSync' in page
    assert 'const checkinButton' not in page


def test_unknown_response_remains_in_activity_without_removed_sections():
    snapshot = fixture()
    snapshot['conversations'][0].update(awaiting_response=None, coverage='partial',
                                        review_requested=False)
    result = board.render(snapshot, CONFIG, BRAIN, rendered_at=STAMP)
    page = result['index.html']
    activity = page.split('id="activity"')[1].split('id="coverage"')[0]
    assert snapshot['conversations'][0]['url'] in activity
    assert page.count('<details class="topic">') == 1
    for surface in (page, result['dashboard.md']):
        assert 'Unknown response state' not in surface
        assert 'Following through' not in surface
    assert 'href="#unknown"' not in page
    assert 'href="#follow-through"' not in page
    assert any(item['state'] == 'unknown' for item in json.loads(result['state.json'])['items'])
