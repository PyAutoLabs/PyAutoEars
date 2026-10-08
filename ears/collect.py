"""Deterministic, public-only GitHub evidence. No mutations or model calls."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
BROADCAST = {"Announcements", "Show and tell"}
DISCUSSION_COMMENTS = """query($owner:String!, $name:String!, $number:Int!, $after:String) {
  repository(owner:$owner, name:$name) { discussion(number:$number) {
    comments(first:100, after:$after) {
      nodes { id databaseId body createdAt deletedAt author { login __typename } }
      pageInfo { hasNextPage endCursor }
    }
  } }
}"""
DISCUSSION_REPLIES = """query($id:ID!, $after:String) {
  node(id:$id) { ... on DiscussionComment {
    replies(first:100, after:$after) {
      nodes { id databaseId body createdAt deletedAt author { login __typename } }
      pageInfo { hasNextPage endCursor }
    }
  } }
}"""

DISCUSSION_STATE = """query($owner:String!, $name:String!, $number:Int!) {
  repository(owner:$owner, name:$name) { discussion(number:$number) {
    closed closedAt answerChosenAt
  } }
}"""


def utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc).isoformat()


def source_timestamp(value):
    """Keep valid public source dates; absent or malformed metadata is unknown."""
    try:
        return utc(value).isoformat()
    except (ValueError, TypeError):
        return None


def line(value):
    return " ".join(str(value or "").split())[:500]


def repository(value):
    if not isinstance(value, str) or not REPO.fullmatch(value):
        raise ValueError("invalid repository identity")
    return value


def homes(mind):
    # Identity is owned by Mind, never duplicated in an Ears registry.
    import yaml
    data = yaml.safe_load((Path(mind) / "repos.yaml").read_text())
    rows = data.get("repos", data.get("repositories", {}))
    if not isinstance(rows, dict):
        raise ValueError("body map has no repository mapping")
    result = sorted({repository(v["github"]) for v in rows.values()
                     if isinstance(v, dict) and v.get("github")})
    if not result:
        raise ValueError("body map contains no GitHub homes")
    return result


class ReadError(Exception):
    """Bounded public description, never an API payload or secret."""


class GitHub:
    def __init__(self, binary="gh"):
        self.binary = binary

    def get(self, endpoint):
        if not endpoint.startswith("repos/") or ".." in endpoint.split("/"):
            raise ReadError("unsupported read endpoint")
        try:
            r = subprocess.run([self.binary, "api", "--method", "GET", endpoint],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise ReadError("GitHub client unavailable or timed out") from None
        if r.returncode:
            raise ReadError("GitHub read failed (permissions, rate limit or endpoint)")
        try:
            return json.loads(r.stdout)
        except ValueError:
            raise ReadError("invalid JSON response") from None

    def discussion_state(self, repo, number):
        owner, name = repository(repo).split("/")
        payload = json.dumps({"query": DISCUSSION_STATE,
                              "variables": {"owner": owner, "name": name, "number": number}})
        try:
            r = subprocess.run([self.binary, "api", "graphql", "--input", "-"],
                               input=payload, capture_output=True, text=True, timeout=60)
            result = json.loads(r.stdout)
            if r.returncode or not isinstance(result, dict) or result.get("errors"):
                raise ReadError("Discussion settlement read failed")
            detail = result["data"]["repository"]["discussion"]
            if not isinstance(detail, dict) or type(detail.get("closed")) is not bool:
                raise ReadError("Discussion settlement unavailable")
            return detail
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            raise ReadError("Discussion settlement unavailable") from None

    def discussion_page(self, repo, number, after=None, comment_id=None):
        """Only these fixed queries are allowed; source text is never executable."""
        owner, name = repository(repo).split("/")
        query = DISCUSSION_REPLIES if comment_id else DISCUSSION_COMMENTS
        variables = {"id": comment_id} if comment_id else {
            "owner": owner, "name": name, "number": number}
        if after is not None:
            variables["after"] = after
        payload = json.dumps({"query": query, "variables": variables})
        try:
            r = subprocess.run([self.binary, "api", "graphql", "--input", "-"],
                               input=payload, capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise ReadError("Discussion GraphQL read failed (permissions, rate limit or endpoint)")
            result = json.loads(r.stdout)
            if not isinstance(result, dict) or result.get("errors"):
                raise ReadError("Discussion GraphQL returned incomplete evidence")
            data = result["data"]
            return data["node"]["replies"] if comment_id else data["repository"]["discussion"]["comments"]
        except (OSError, subprocess.TimeoutExpired):
            raise ReadError("Discussion GraphQL client unavailable or timed out") from None
        except (ValueError, KeyError, TypeError):
            raise ReadError("invalid Discussion GraphQL response") from None


def discussion_connection(api, repo, number, cap, comment_id=None):
    rows, seen, cursor = [], set(), None
    if not hasattr(api, "discussion_page"):
        return rows, False, "Discussion GraphQL adapter unavailable"
    for _ in range(cap):
        try:
            data = api.discussion_page(repo, number, cursor, comment_id)
        except ReadError as exc:
            return rows, False, str(exc)
        if not isinstance(data, dict) or not isinstance(data.get("nodes"), list):
            return rows, False, "invalid Discussion connection"
        # Null nodes may represent deleted/inaccessible activity. Keep the gap.
        if any(not isinstance(x, dict) for x in data["nodes"]):
            rows.extend(x for x in data["nodes"] if isinstance(x, dict))
            return rows, False, "Discussion activity contains an unavailable node"
        rows.extend(data["nodes"])
        info = data.get("pageInfo")
        if not isinstance(info, dict) or type(info.get("hasNextPage")) is not bool:
            return rows, False, "invalid Discussion pagination metadata"
        if not info["hasNextPage"]:
            return rows, True, None
        cursor = info.get("endCursor")
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            return rows, False, "Discussion pagination cursor missing or repeated"
        seen.add(cursor)
    return rows, False, "Discussion page budget reached; additional entries may exist"


def discussion_activity(api, repo, number, cap):
    comments, complete, reason = discussion_connection(api, repo, number, cap)
    gaps = [reason] if reason else []
    activity = list(comments)
    for comment in comments:
        identity = comment.get("id")
        if not isinstance(identity, str) or not identity:
            complete = False
            gaps.append("Discussion comment identity unavailable")
            continue
        replies, ok, why = discussion_connection(api, repo, number, cap, identity)
        activity.extend(replies)
        complete &= ok
        if why:
            gaps.append(why)
    normalized = [{"created_at": x.get("createdAt"), "deleted_at": x.get("deletedAt"),
                   "body": x.get("body"), "id": x.get("databaseId"),
                   "user": {"login": x["author"].get("login"),
                            "type": x["author"].get("__typename")}
                   if isinstance(x.get("author"), dict) else None} for x in activity]
    if not complete:
        # REST can preserve observed activity, but cannot erase the GraphQL gap.
        fallback, _, why = pages(api, f"repos/{repo}/discussions/{number}/comments", cap)
        normalized.extend(fallback)
        if why:
            gaps.append(why)
    return normalized, complete, list(dict.fromkeys(gaps))


def pages(api, endpoint, cap):
    items = []
    for page in range(1, cap + 1):
        sep = "&" if "?" in endpoint else "?"
        try:
            data = api.get(f"{endpoint}{sep}per_page=100&page={page}")
        except ReadError as exc:
            return items, False, str(exc)
        if not isinstance(data, list) or any(not isinstance(x, dict) for x in data):
            return items, False, "invalid list response"
        items.extend(data)
        if len(data) < 100:
            return items, True, None
    return items, False, "page budget reached; additional entries may exist"


def human(user):
    return isinstance(user, dict) and isinstance(user.get("login"), str) and bool(user["login"]) and user.get("type") != "Bot" \
        and not user["login"].endswith("[bot]")


def activity_events(entries):
    events, gaps = [], []
    for entry in entries:
        actor = entry.get("user")
        if entry.get("state") == "PENDING":
            continue
        if entry.get("deleted_at") or not isinstance(actor, dict) or not isinstance(actor.get("login"), str) or not actor["login"]:
            gaps.append("activity author deleted or unavailable")
        elif human(actor):
            events.append((entry.get("submitted_at") or entry.get("created_at"), actor["login"]))
    return events, list(dict.fromkeys(gaps))


def waiting(events, selves):
    """Oldest external message since the latest maintainer message.

    This is a response heuristic, not proof an issue is solved. A missing
    event time cannot establish ordering, so the result is unknown.
    """
    try:
        ordered = sorted((utc(t), who) for t, who in events if who)
    except (ValueError, TypeError):
        return None, None
    pending = None
    previous = None
    for when, who in ordered:
        actor = who.casefold()
        if previous and previous[0] == when and previous[1] != actor:
            return None, None
        previous = (when, actor)
        if actor in selves:
            pending = None
        elif pending is None:
            pending = when.isoformat()
    return bool(pending), pending


def follow_up(raw, comments, kind, selves, complete, url):
    """Post-settlement human activity, never a semantic actionability verdict."""
    unknown = {"review_needed": None, "since": None, "url": None}
    markers = []
    if raw.get("state") == "closed":
        markers.append(raw.get("closed_at"))
    if kind == "discussion" and raw.get("answer_chosen_at") is not None:
        markers.append(raw["answer_chosen_at"])
    try:
        boundary = max(utc(t) for t in markers)
        events, gaps = activity_events(comments)
        if not complete or gaps:
            return unknown
        # Parse every event before filtering, so missing times cannot hide activity.
        later = [(t, who) for t, who in events if utc(t) > boundary]
        needed, since = waiting(later, selves)
        if needed is None:
            return unknown
        link = None
        if needed:
            candidate = next(c for c in comments if human(c.get("user"))
                             and c["user"]["login"].casefold() not in selves
                             and utc(c.get("created_at")) == utc(since))
            identity = candidate.get("id")
            anchor = "discussioncomment" if kind == "discussion" else "issuecomment"
            link = url + (f"#{anchor}-{identity}" if type(identity) is int and identity > 0 else "")
        return {"review_needed": needed, "since": since, "url": link}
    except (ValueError, TypeError, StopIteration):
        return unknown


def validate_follow_up(row):
    if "follow_up" not in row:
        return
    f = row["follow_up"]
    if not isinstance(f, dict) or set(f) != {"review_needed", "since", "url"}:
        raise ValueError("invalid follow-up observation")
    if f["review_needed"] is not None and type(f["review_needed"]) is not bool:
        raise ValueError("invalid follow-up state")
    if row["kind"] not in {"issue", "discussion"} or not (row.get("closed") or row["answered"]):
        raise ValueError("follow-up lacks settled thread")
    if f["review_needed"] is True:
        utc(f["since"])
        anchor = "discussioncomment" if row["kind"] == "discussion" else "issuecomment"
        if not isinstance(f["url"], str) or not re.fullmatch(re.escape(row["url"]) + rf"(#{anchor}-[1-9][0-9]*)?", f["url"]):
            raise ValueError("invalid follow-up source")
        if row["coverage"] != "complete" or row["awaiting_response"] is not True or row["waiting_since"] != f["since"]:
            raise ValueError("inconsistent follow-up evidence")
    elif f["since"] is not None or f["url"] is not None:
        raise ValueError("inactive follow-up carries candidate")
    if row["awaiting_response"] is not f["review_needed"]:
        raise ValueError("inconsistent follow-up response")


def conversation(api, repo, raw, kind, config, deliveries=None, pending=None):
    number = raw.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ReadError("invalid conversation number")
    path = "discussions" if kind == "discussion" else "issues"
    prefix = f"repos/{repo}/{path}/{number}"
    if kind == "discussion":
        comments, complete, gaps = discussion_activity(api, repo, number, config["max_pages"])
    else:
        comments, complete, reason = pages(api, prefix + "/comments", config["max_pages"])
        gaps = [reason] if reason else []
    events, missing = activity_events([raw] + comments)
    gaps.extend(missing)
    complete &= not missing
    reviewers = []
    if kind == "pr":
        for endpoint in ("comments", "reviews"):
            entries, ok, why = pages(api, f"repos/{repo}/pulls/{number}/{endpoint}", config["max_pages"])
            complete &= ok
            if why:
                gaps.append(why)
            review_events, missing = activity_events(entries)
            events.extend(review_events)
            gaps.extend(missing)
            complete &= not missing
        try:
            detail = api.get(f"repos/{repo}/pulls/{number}")
            reviewers = [x["login"].casefold() for x in detail.get("requested_reviewers", [])]
        except (ReadError, AttributeError, KeyError, TypeError):
            complete = False
            gaps.append("requested reviewers unavailable")
    selves = {x.casefold() for x in config["self_logins"]}
    awaiting, since = waiting(events, selves) if complete else (None, None)
    if complete and awaiting is None:
        complete = False
        gaps.append("activity timestamps unavailable or ordering ambiguous")
    category = (raw.get("category") or {}).get("name")
    answered = raw.get("answer_chosen_at") is not None
    observation = None
    settled = raw.get("state") == "closed" or (kind == "discussion" and answered)
    if kind != "pr" and settled and category not in BROADCAST:
        # REST Discussions omit closed_at. Missing/unreadable GraphQL evidence
        # must never turn a closed thread into a checked-clear observation.
        if kind == "discussion" and raw.get("state") == "closed" and not raw.get("closed_at"):
            try:
                detail = api.discussion_state(repo, number)
                graph_answer = detail.get("answerChosenAt")
                rest_answer = raw.get("answer_chosen_at")
                same_answer = ((graph_answer is None and rest_answer is None) or
                               (graph_answer is not None and rest_answer is not None and
                                utc(graph_answer) == utc(rest_answer)))
                if not detail["closed"] or not same_answer:
                    raise ReadError("Discussion settlement changed during collection")
                raw = dict(raw, closed_at=detail.get("closedAt"))
            except (AttributeError, KeyError, TypeError, ValueError, ReadError):
                complete = False
                gaps.append("Discussion settlement unavailable or changed during collection")
        observation = follow_up(raw, comments, kind, selves, complete,
                                f"https://github.com/{repo}/{path}/{number}")
        awaiting, since = observation["review_needed"], observation["since"]
        if awaiting is None:
            complete = False
            gaps.append("post-settlement activity or settlement time unknown")
    elif kind == "discussion" and (category in BROADCAST or raw.get("locked")):
        awaiting, since = False, None
    if kind == "discussion" and deliveries is not None:
        from .followthrough import derive
        deliveries.append(derive(api, f"https://github.com/{repo}/discussions/{number}",
                                 [raw] + comments, config, complete, pending))
    url_kind = "pull" if kind == "pr" else path
    return {
        "id": f"{repo}/{url_kind}/{number}", "repo": repo, "number": number,
        "kind": kind, "url": f"https://github.com/{repo}/{url_kind}/{number}",
        "title": line(raw.get("title")) or "Untitled conversation",
        "closed": raw.get("state") == "closed",
        "author": line((raw.get("user") or {}).get("login")),
        "category": line(category), "answered": answered,
        "created_at": source_timestamp(raw.get("created_at")),
        "updated_at": source_timestamp(raw.get("updated_at")),
        "awaiting_response": awaiting, "waiting_since": since,
        "review_requested": bool(selves.intersection(reviewers)),
        "coverage": "complete" if complete and awaiting is not None else "partial",
        "gaps": gaps, "cached": False,
        "feedback_report": "<!-- feedback-report: v1 -->" in (raw.get("body") or ""),
        **({"follow_up": observation} if observation is not None else {}),
    }


def quiet_closed_issue(entry):
    """Avoid rereading historical comment threads with no post-closure update."""
    if entry.get("state") != "closed" or "pull_request" in entry:
        return False
    if type(entry.get("comments")) is int and entry["comments"] == 0:
        return True
    try:
        return utc(entry.get("updated_at")) == utc(entry.get("closed_at"))
    except (ValueError, TypeError):
        return False


def collect(api, repo_homes, config, pending=None):
    hub = repository(config["hub"])
    selves = {x.casefold() for x in config["self_logins"]}
    stamp = now()
    rows, receipts, deliveries = [], [], []
    for repo in sorted(set(repo_homes) | {hub}):
        repository(repo)
        receipt = {"repo": repo, "checked_at": stamp, "status": "unavailable",
                   "public_verified": False, "gaps": []}
        receipts.append(receipt)
        try:
            meta = api.get(f"repos/{repo}")
            if not isinstance(meta, dict) or meta.get("private") is not False:
                receipt["status"] = "excluded"
                receipt["gaps"] = ["source is not verified public"]
                continue
        except ReadError as exc:
            receipt["gaps"] = [str(exc)]
            continue
        receipt["public_verified"] = True
        kinds = [("issues", "issue")]
        if repo == hub:
            kinds.append(("discussions", "discussion"))
        source_rows = []
        for endpoint, kind in kinds:
            entries, complete, why = pages(api, f"repos/{repo}/{endpoint}?state=open", config["max_pages"])
            if why:
                receipt["gaps"].append(f"{endpoint}: {why}")
            # Recent activity, not creation time, determines the bounded sweep.
            closed_endpoint = f"repos/{repo}/{endpoint}?state=closed&sort=updated&direction=desc"
            closed, _, gap = pages(api, closed_endpoint, config["max_pages"])
            entries.extend(e for e in closed if kind == "discussion" or "pull_request" not in e)
            entries = list({e.get("number"): e for e in entries}.values())
            if gap:
                receipt["gaps"].append(f"closed {endpoint}: {gap}")
            for entry in entries:
                if kind == "issue" and quiet_closed_issue(entry):
                    continue
                if kind != "discussion" and "pull_request" in entry and (entry.get("state", "open") != "open" or entry.get("locked")):
                    continue
                item_kind = "pr" if "pull_request" in entry else kind
                is_human = human(entry.get("user"))
                known_bot = isinstance(entry.get("user"), dict) and (
                    entry["user"].get("type") == "Bot" or
                    str(entry["user"].get("login", "")).endswith("[bot]"))
                if known_bot and item_kind != "pr":
                    continue
                external = is_human and entry["user"]["login"].casefold() not in selves
                if item_kind == "issue" and is_human and not external and entry.get("state") != "closed":
                    continue
                try:
                    row = conversation(api, repo, entry, item_kind, config, deliveries, pending)
                except ReadError as exc:
                    receipt["gaps"].append(str(exc))
                    continue
                if row["coverage"] != "complete":
                    receipt["gaps"].append(f"{item_kind} #{row['number']}: incomplete activity")
                # Self-authored PRs matter only for a requested review; unknown
                # review coverage stays visible rather than silently dropping it.
                if item_kind == "pr" and not external and not row["review_requested"] \
                        and row["coverage"] == "complete":
                    continue
                # Quiet closed issues add no queue value; keep unknowns visible.
                if item_kind == "issue" and row.get("closed") and row["awaiting_response"] is False:
                    continue
                source_rows.append(row)
        receipt["status"] = "partial" if receipt["gaps"] else "complete"
        rows.extend(source_rows)
    return {"schema_version": 1, "generated": stamp,
            "conversations": list({r["id"]: r for r in rows}.values()),
            "receipts": receipts, "follow_through": deliveries}


def validate(snapshot):
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != 1:
        raise ValueError("unsupported community snapshot")
    utc(snapshot.get("generated"))
    required = {"schema_version", "generated", "conversations", "receipts"}
    if not required <= set(snapshot) or set(snapshot) - required - {"follow_through"}:
        raise ValueError("unknown snapshot fields; raw content must not be published")
    receipts = snapshot.get("receipts")
    rows = snapshot.get("conversations")
    if not isinstance(receipts, list) or not isinstance(rows, list):
        raise ValueError("missing conversations or receipts")
    public = set()
    for receipt in receipts:
        if not isinstance(receipt, dict):
            raise ValueError("invalid coverage receipt")
        if set(receipt) != {"repo", "checked_at", "status", "public_verified", "gaps"}:
            raise ValueError("unknown receipt fields")
        repo = repository(receipt.get("repo"))
        utc(receipt.get("checked_at"))
        if receipt.get("status") not in {"complete", "partial", "unavailable", "excluded"}:
            raise ValueError("invalid coverage state")
        if not isinstance(receipt.get("gaps"), list) or any(not isinstance(x, str) for x in receipt["gaps"]):
            raise ValueError("invalid coverage gaps")
        if receipt["status"] in {"complete", "partial"} and receipt.get("public_verified") is not True:
            raise ValueError("read source must be verified public")
        if receipt.get("public_verified") is True:
            public.add(repo)
    ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid conversation")
        if set(row) - {"closed", "follow_up", "created_at", "updated_at"} != {"id", "repo", "number", "kind", "url", "title", "author", "category", "answered",
                        "awaiting_response", "waiting_since", "review_requested", "coverage", "gaps", "cached", "feedback_report"}:
            raise ValueError("unknown conversation fields; raw content must not be published")
        if "closed" in row and type(row["closed"]) is not bool:
            raise ValueError("invalid closed state")
        if row.get("repo") not in public:
            raise ValueError("conversation lacks a public-source receipt")
        if row.get("kind") not in {"issue", "pr", "discussion"}:
            raise ValueError("invalid conversation kind")
        n = row.get("number")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError("invalid conversation number")
        suffix = {"issue": "issues", "pr": "pull", "discussion": "discussions"}[row["kind"]]
        identity = f"{row['repo']}/{suffix}/{n}"
        if row.get("id") != identity or row.get("url") != f"https://github.com/{identity}" or identity in ids:
            raise ValueError("invalid or duplicate conversation identity/link")
        ids.add(identity)
        validate_follow_up(row)
        if row.get("awaiting_response") is not None and type(row["awaiting_response"]) is not bool:
            raise ValueError("invalid awaiting-response state")
        if row.get("waiting_since"):
            utc(row["waiting_since"])
        for key in ("created_at", "updated_at"):
            if row.get(key) is not None:
                utc(row[key])
        if row.get("coverage") not in {"complete", "partial"}:
            raise ValueError("invalid conversation coverage")
        for key in ("title", "author", "category"):
            if not isinstance(row.get(key), str):
                raise ValueError(f"invalid conversation {key}")
        for key in ("review_requested", "answered", "cached", "feedback_report"):
            if type(row.get(key)) is not bool:
                raise ValueError(f"invalid conversation {key}")
    if "follow_through" in snapshot:
        from .followthrough import validate as validate_delivery
        validate_delivery(snapshot["follow_through"], rows)
    return snapshot
