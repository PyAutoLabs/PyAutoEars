import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ears import board, collect
from ears.cli import main

CONFIG = json.loads((ROOT / "config.json").read_text()) | {
    "hub": "example/hub", "self_logins": ["Maintainer", "Second"], "max_pages": 2,
}
BRAIN = ROOT.parent / "PyAutoBrain"
STAMP = "2026-10-03T12:00:00Z"


def user(login):
    return {"login": login, "type": "User"}


def thread(number=1, login="Reporter", **kw):
    return {"number": number, "title": "Help with imaging", "user": user(login),
            "created_at": "2026-10-01T12:00:00Z", "state": "open", **kw}


class API:
    def __init__(self, overrides=None):
        self.overrides = overrides or {}
        self.calls = []

    def get(self, path):
        self.calls.append(path)
        value = self.overrides.get(path)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return copy.deepcopy(value)
        if "?" in path:
            return []
        if "/pulls/" in path:
            return {"requested_reviewers": []}
        return {"private": False}


def listing(repo="example/lib", kind="issues", page=1):
    return f"repos/{repo}/{kind}?state=open&per_page=100&page={page}"


def comments(repo="example/lib", kind="issues", n=1, page=1):
    return f"repos/{repo}/{kind}/{n}/comments?per_page=100&page={page}"


def fixture():
    s = collect.collect(API({listing(): [thread()]}), ["example/lib"], CONFIG)
    s["generated"] = STAMP
    for r in s["receipts"]:
        r["checked_at"] = STAMP
    return s


@pytest.mark.parametrize('kind', ['issue', 'pr', 'discussion'])
def test_source_dates_are_normalized_independently_of_response_timing(kind):
    raw = thread(created_at='2026-10-01T13:00:00+01:00', updated_at=STAMP)
    if kind == 'pr':
        raw['pull_request'] = {}
    repo = 'example/hub' if kind == 'discussion' else 'example/lib'
    endpoint = 'discussions' if kind == 'discussion' else 'issues'
    snapshot = collect.collect(API({listing(repo, endpoint): [raw]}), ['example/lib'], CONFIG)
    row = snapshot['conversations'][0]
    assert row['kind'] == kind
    assert row['created_at'] == '2026-10-01T12:00:00+00:00'
    assert row['updated_at'] == '2026-10-03T12:00:00+00:00'
    collect.validate(snapshot)
    row['updated_at'] = '<script>bad date</script>'
    with pytest.raises(ValueError):
        collect.validate(snapshot)


@pytest.mark.parametrize('value', [None, '', 'not a date', '2026-10-01T12:00:00', 42])
def test_unusable_source_dates_are_unknown(value):
    snapshot = collect.collect(API({listing(): [thread(updated_at=value)]}), ['example/lib'], CONFIG)
    assert snapshot['conversations'][0]['updated_at'] is None
    collect.validate(snapshot)


def test_public_only_and_failed_metadata_never_leak_titles():
    api = API({"repos/private/lib": {"private": True},
               "repos/unknown/lib": collect.ReadError("read unavailable"),
               listing("private/lib"): [thread(title="PRIVATE TITLE")]})
    s = collect.collect(api, ["private/lib", "unknown/lib"], CONFIG)
    assert not s["conversations"]
    assert listing("private/lib") not in api.calls
    assert "PRIVATE TITLE" not in json.dumps(s)
    assert {r["status"] for r in s["receipts"]} == {"complete", "excluded", "unavailable"}


def test_pagination_and_oldest_conversation_beyond_thirty():
    api = API({listing(): [thread(n) for n in range(1, 101)],
               listing(page=2): [thread(101, created_at="2020-01-01T00:00:00Z")]})
    s = collect.collect(api, ["example/lib"], CONFIG)
    assert len(s["conversations"]) == 101
    assert all(r["awaiting_response"] for r in s["conversations"])
    assert comments(n=101) in api.calls
    assert not any(r["gaps"] for r in s["receipts"])


@pytest.mark.parametrize("second", [collect.ReadError("page failed"), [thread(n) for n in range(101, 201)]])
def test_partial_page_or_cap_keeps_evidence_and_exposes_gap(second):
    api = API({listing(): [thread(n) for n in range(1, 101)], listing(page=2): second})
    s = collect.collect(api, ["example/lib"], CONFIG)
    r = next(r for r in s["receipts"] if r["repo"] == "example/lib")
    assert r["status"] == "partial" and r["gaps"]
    assert len(s["conversations"]) >= 100


def test_comment_failure_is_unknown_not_clear():
    s = collect.collect(API({listing(): [thread()], comments(): collect.ReadError("unavailable")}), ["example/lib"], CONFIG)
    row = s["conversations"][0]
    assert row["awaiting_response"] is None and row["waiting_since"] is None
    assert row["coverage"] == "partial"


def test_pr_review_reply_and_multiple_maintainers_settle_wait():
    api = API({listing(): [thread(pull_request={"url": "unused"})],
               comments(kind="pulls"): [{"user": user("SECOND"), "created_at": "2026-10-02T00:00:00Z"}],
               "repos/example/lib/pulls/1": {"requested_reviewers": [user("Maintainer")]}})
    row = collect.collect(api, ["example/lib"], CONFIG)["conversations"][0]
    assert row["awaiting_response"] is False
    assert row["review_requested"] is True


def test_response_age_is_not_generic_updated_at():
    api = API({listing(): [thread(updated_at="2026-10-03T12:00:00Z")],
               comments(): [{"user": user("Maintainer"), "created_at": "2026-10-02T00:00:00Z"},
                            {"user": user("Reporter"), "created_at": "2026-10-02T01:00:00Z"},
                            {"user": user("Reporter"), "created_at": "2026-10-02T05:00:00Z"}]})
    row = collect.collect(api, ["example/lib"], CONFIG)["conversations"][0]
    assert row["waiting_since"] == "2026-10-02T01:00:00+00:00"


@pytest.mark.parametrize("category,answer,expected", [("Help & Questions", None, None), ("Ideas & Proposals", STAMP, None), ("Show and tell", None, False)])
def test_discussion_policy_and_unverified_nested_replies(category, answer, expected):
    api = API({listing("example/hub", "discussions"): [thread(category={"name": category}, answer_chosen_at=answer)]})
    row = collect.collect(api, [], CONFIG)["conversations"][0]
    assert row["awaiting_response"] is expected
    assert row["coverage"] == "partial"


def test_raw_body_and_secret_are_not_in_snapshot():
    api = API({listing(): [thread(body="<!-- feedback-report: v1 --> SECRET raw transcript")]})
    s = collect.collect(api, ["example/lib"], CONFIG)
    assert s["conversations"][0]["feedback_report"]
    assert "SECRET" not in json.dumps(s)


def test_invalid_timestamp_does_not_invent_response_order():
    assert collect.waiting([("invalid", "Reporter")], {"maintainer"}) == (None, None)
    assert collect.waiting([(STAMP, "Reporter"), (STAMP, "Maintainer")], {"maintainer"}) == (None, None)


def test_snapshot_validation_rejects_private_unattested_and_bad_urls():
    for mutate in (lambda s: s["receipts"].clear(),
                   lambda s: s["conversations"][0].update(url="javascript:alert(1)"),
                   lambda s: s.update(schema_version=True),
                   lambda s: s["conversations"][0].update(body="raw private content"),
                   lambda s: s["conversations"].append(copy.deepcopy(s["conversations"][0]))):
        s = fixture()
        mutate(s)
        with pytest.raises(ValueError):
            collect.validate(s)


def test_html_escapes_titles_and_portable_actions():
    s = fixture()
    s["conversations"][0]["title"] = '<img src=x onerror="alert(1)"> [fake](javascript:alert(1))'
    result = board.render(s, CONFIG, BRAIN, rendered_at=STAMP)
    page = result["index.html"]
    assert '<img src=x' not in page
    assert '&lt;img' in page
    assert 'href="javascript:' not in page
    assert "navigator.clipboard.writeText" in page and "Copy unavailable" in page
    contract = board.load_module(BRAIN / "board/copy_contract.py", "copy_contract")
    contract.assert_portable_copy_payloads(page)
    state = json.loads(result["state.json"])
    assert state["organ"] == "ears" and state["status"] == "yellow"
    assert not board.presentation(BRAIN)[1].validate_state(state)


@pytest.mark.parametrize("case,expected", [("empty", "grey"), ("fresh", "green"), ("stale", "stale"), ("partial", "yellow")])
def test_board_status_never_conflates_unknown_and_zero(case, expected):
    s = fixture()
    s["conversations"] = []
    rendered = STAMP
    if case == "empty":
        s["receipts"] = []
    if case == "stale":
        rendered = "2026-10-04T00:00:00Z"
    if case == "partial":
        s["receipts"][0].update(status="partial", gaps=["unavailable"])
    result = board.render(s, CONFIG, BRAIN, rendered_at=rendered)
    assert json.loads(result["state.json"])["status"] == expected
    assert 'id="follow-through"' not in result["index.html"]


def test_cli_round_trip_and_invalid_input(tmp_path):
    source = tmp_path / "snapshot.json"
    source.write_text(json.dumps(fixture()))
    output = tmp_path / "site"
    assert main(["check", "--snapshot", str(source)]) == 0
    assert main(["board", "--snapshot", str(source), "--brain", str(BRAIN), "--output", str(output)]) == 0
    assert (output / "state.json").exists()
    source.write_text("not json")
    assert main(["check", "--snapshot", str(source)]) == 2
    assert main(["board"]) == 2


def test_body_map_and_repository_validation(tmp_path):
    (tmp_path / "repos.yaml").write_text("repos:\n  Lib:\n    github: example/lib\n")
    assert collect.homes(tmp_path) == ["example/lib"]
    with pytest.raises(ValueError):
        collect.repository("../../etc/passwd")


def test_gh_adapter_only_uses_get(monkeypatch):
    calls = []
    def run(args, **kw):
        calls.append(args)
        return type("Result", (), {"returncode": 0, "stdout": "[]"})()
    monkeypatch.setattr(collect.subprocess, "run", run)
    assert collect.GitHub().get("repos/example/lib/issues") == []
    assert calls == [["gh", "api", "--method", "GET", "repos/example/lib/issues"]]
    with pytest.raises(collect.ReadError):
        collect.GitHub().get("https://example.invalid/upload")


def test_bot_pr_requested_review_is_not_lost():
    pr = thread(login="bot[bot]", pull_request={"url": "unused"})
    pr["user"]["type"] = "Bot"
    api = API({listing(): [pr], "repos/example/lib/pulls/1": {"requested_reviewers": [user("Second")]}})
    row = collect.collect(api, ["example/lib"], CONFIG)["conversations"][0]
    assert row["review_requested"] is True and row["awaiting_response"] is False


def test_panel_refresh_uses_snapshot_capture_and_owner_workflow(monkeypatch):
    theme = board.presentation(BRAIN)[0]
    calls = []
    monkeypatch.setattr(theme, "orchestration_panel", lambda *a, **kw: calls.append(kw) or "")
    monkeypatch.setattr(board, "presentation", lambda brain: (theme, board.load_module(BRAIN / "board/_state.py", "freshness_state")))
    snap = fixture()
    board.render(snap, CONFIG, BRAIN, rendered_at="2026-10-07T12:00:00Z")
    assert calls[0]["refreshed_at"] == snap["generated"]
    assert calls[0]["refresh_url"] == f"https://github.com/{CONFIG['repo']}/actions/workflows/pages.yml"

    for status in ("partial", "unavailable"):
        snap["receipts"][0]["status"] = status
        board.render(snap, CONFIG, BRAIN, rendered_at=STAMP)
        assert calls[-1]["refreshed_at"] is None
    for receipt in snap["receipts"]:
        receipt["status"] = "excluded"
    board.render(snap, CONFIG, BRAIN, rendered_at=STAMP)
    assert calls[-1]["refreshed_at"] is None
    snap["receipts"] = []
    snap["conversations"] = []
    board.render(snap, CONFIG, BRAIN, rendered_at=STAMP)
    assert calls[-1]["refreshed_at"] is None
