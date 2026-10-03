"""Deterministic, public-only GitHub evidence. No mutations or model calls."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
BROADCAST = {"Announcements", "Show and tell"}


def utc(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed.astimezone(timezone.utc)


def now():
    return datetime.now(timezone.utc).isoformat()


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
    return bool(user and user.get("login")) and user.get("type") != "Bot" \
        and not user["login"].endswith("[bot]")


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


def conversation(api, repo, raw, kind, config):
    number = raw.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ReadError("invalid conversation number")
    path = "discussions" if kind == "discussion" else "issues"
    prefix = f"repos/{repo}/{path}/{number}"
    comments, complete, reason = pages(api, prefix + "/comments", config["max_pages"])
    gaps = [reason] if reason else []
    if kind == "discussion":
        # The available REST contract does not prove recursive reply coverage.
        # Keep the source visibly partial until an adapter can establish it.
        complete = False
        gaps.append("nested discussion replies not independently verified")
    events = [(raw.get("created_at"), raw["user"]["login"])] if human(raw.get("user")) else []
    events += [(x.get("created_at"), x["user"]["login"]) for x in comments
               if human(x.get("user"))]
    reviewers = []
    if kind == "pr":
        for endpoint in ("comments", "reviews"):
            entries, ok, why = pages(api, f"repos/{repo}/pulls/{number}/{endpoint}", config["max_pages"])
            complete &= ok
            if why:
                gaps.append(why)
            events += [(x.get("submitted_at") or x.get("created_at"), x["user"]["login"])
                       for x in entries if human(x.get("user"))
                       and x.get("state") != "PENDING"]
        try:
            detail = api.get(f"repos/{repo}/pulls/{number}")
            reviewers = [x["login"].casefold() for x in detail.get("requested_reviewers", [])]
        except (ReadError, AttributeError, KeyError, TypeError):
            complete = False
            gaps.append("requested reviewers unavailable")
    selves = {x.casefold() for x in config["self_logins"]}
    awaiting, since = waiting(events, selves) if complete else (None, None)
    category = (raw.get("category") or {}).get("name")
    answered = raw.get("answer_chosen_at") is not None
    # Preserve the established hub policy; delivery follow-up is separate.
    if kind == "discussion" and (answered or category in BROADCAST):
        awaiting, since = False, None
    url_kind = "pull" if kind == "pr" else path
    return {
        "id": f"{repo}/{url_kind}/{number}", "repo": repo, "number": number,
        "kind": kind, "url": f"https://github.com/{repo}/{url_kind}/{number}",
        "title": line(raw.get("title")) or "Untitled conversation",
        "author": line((raw.get("user") or {}).get("login")),
        "category": line(category), "answered": answered,
        "awaiting_response": awaiting, "waiting_since": since,
        "review_requested": bool(selves.intersection(reviewers)),
        "coverage": "complete" if complete and awaiting is not None else "partial",
        "gaps": gaps, "cached": False,
        "feedback_report": "<!-- feedback-report: v1 -->" in (raw.get("body") or ""),
    }


def collect(api, repo_homes, config):
    hub = repository(config["hub"])
    selves = {x.casefold() for x in config["self_logins"]}
    stamp = now()
    rows, receipts = [], []
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
            for entry in entries:
                if entry.get("state", "open") != "open" or entry.get("locked"):
                    continue
                item_kind = "pr" if entry.get("pull_request") else kind
                is_human = human(entry.get("user"))
                if not is_human and item_kind != "pr":
                    continue
                external = is_human and entry["user"]["login"].casefold() not in selves
                if item_kind == "issue" and not external:
                    continue
                try:
                    row = conversation(api, repo, entry, item_kind, config)
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
                source_rows.append(row)
        receipt["status"] = "partial" if receipt["gaps"] else "complete"
        rows.extend(source_rows)
    return {"schema_version": 1, "generated": stamp,
            "conversations": list({r["id"]: r for r in rows}.values()),
            "receipts": receipts}


def validate(snapshot):
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot.get("schema_version") != 1:
        raise ValueError("unsupported community snapshot")
    utc(snapshot.get("generated"))
    if set(snapshot) != {"schema_version", "generated", "conversations", "receipts"}:
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
        if set(row) != {"id", "repo", "number", "kind", "url", "title", "author", "category", "answered",
                        "awaiting_response", "waiting_since", "review_requested", "coverage", "gaps", "cached", "feedback_report"}:
            raise ValueError("unknown conversation fields; raw content must not be published")
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
        if row.get("awaiting_response") is not None and type(row["awaiting_response"]) is not bool:
            raise ValueError("invalid awaiting-response state")
        if row.get("waiting_since"):
            utc(row["waiting_since"])
        if row.get("coverage") not in {"complete", "partial"}:
            raise ValueError("invalid conversation coverage")
        for key in ("title", "author", "category"):
            if not isinstance(row.get(key), str):
                raise ValueError(f"invalid conversation {key}")
        for key in ("review_requested", "answered", "cached", "feedback_report"):
            if type(row.get(key)) is not bool:
                raise ValueError(f"invalid conversation {key}")
    return snapshot
