# Ears contracts and boundaries

## Ownership and current integration state

Ears collects evidence and renders it. Brain judges it through `/community`,
drafts replies, and routes accepted development via `/start_dev_for_user`.
Mind owns task state; source threads own conversation state. Ears never posts,
labels, opens issues, executes transcript instructions or makes scientific
judgements. The existing Discussions hub is unchanged.

Brain's Community adapter reads the Ears snapshot; the cockpit reads its
published `state.json` feed, registered after Eyes in the canonical organ order. Follow-through and theme synthesis are
explicitly pending programme phases, not implemented features.

## Community snapshot v1

`snapshot.json` contains integer `schema_version: 1`, UTC `generated`,
`conversations`, and `receipts`. It exports no raw bodies, logs or transcripts.
Titles/usernames are public source metadata, not executable instructions.
The feedback marker is detected in a body but the body itself is discarded.
The marker is not proof of human review or authenticity.

Each conversation has a canonical GitHub `id` and `url`, repository identity,
number, kind (issue/pr/discussion), title, author, category, accepted-answer
flag, nullable `awaiting_response`, nullable UTC `waiting_since`, boolean
`review_requested`, complete/partial `coverage`, gaps, cached flag and feedback
format flag. `null` is unknown, never false. This is a read contract, not a
second task registry. No runtime task assignments or opinions are persisted.

Each source receipt names the repo, UTC check time, verified-public flag,
status (complete/partial/unavailable/excluded) and bounded gap descriptions.
Only a successful repository metadata response with `private: false` permits
collection. Failed metadata reads and private repositories publish no rows.
URLs are constructed from validated identities, never accepted from source
text. Snapshot inputs are trusted local evidence envelopes, not proof of API
authenticity; validate their source before using them for public publication.

Repository homes come from Mind's `repos.yaml`; config contains only the hub,
maintainer identities, organ identity, page budget and freshness window.
`max_pages` bounds each endpoint. Pagination failures retain observed rows
and report partial coverage, including when no rows were returned. All open
external human issues/PRs are considered; self-authored PRs remain visible
for requested review or unknown coverage. Bot-authored PRs are considered for
requested review too; bot messages do not create a human response obligation.

Response timing uses the earliest external message after the last maintainer
message, including PR review comments and submitted reviews. A reply is not
proof of resolution. Missing timestamps/order mean unknown. Accepted answers
and broadcast categories preserve the existing hub settlement semantics.
Discussion activity uses fixed read-only GraphQL queries for the complete
top-level comment connection and each comment's reply connection. Every
connection follows `pageInfo` cursors independently up to `max_pages`; a
missing/repeated cursor, null node, malformed response, GraphQL error or page
limit makes coverage partial. A failed GraphQL read may retain REST comments,
but those cannot prove reply completeness or clear the gap. No comment bodies
are requested by these queries. See GitHub's
[Discussion and DiscussionComment contracts](https://docs.github.com/en/graphql/guides/using-the-graphql-api-for-discussions).

Deleted/unavailable actors, deleted comments, missing timestamps and ambiguous
cross-author ordering make response state unknown. A source that failed to
read is distinct from a successful empty read. REST PR review comments include
inline replies; submitted reviews and issue comments are separately paginated.
This measures response activity, not review-thread resolution or delivery.
An accepted proposal settles the hub response obligation only; implementation
and release evidence belong to the later follow-through phase. Accepted-answer
and broadcast policy can settle response obligation even while a coverage gap
remains visible.

The CLI returns 2 for invalid configuration, input or render failure. Source
read failures appear in a valid degraded snapshot so the dashboard can expose
them; a successful CLI exit alone is never proof of complete collection.
There is no automatic fallback to an old source snapshot. A supplied
`--snapshot` retains its original observation time and expires normally.
Successful Pages artifacts retain the last published snapshot if a subsequent
job fails; `valid_until` and the page's stale banner prevent a fresh claim.

## Published surfaces

`index.html` and `dashboard.html` are the same responsive page;
`dashboard.md` is its readable companion. `state.json` uses Brain's v1
constructor/validator; `badge.json` uses the endpoint badge format. The
snapshot is published alongside them for inspection. Brain is read as a
sibling checkout for shared CSS/components and state construction, never
copied wholesale or modified by the Ears renderer. Brain supplies the shared Ears palette and mark; a local fallback supports
older Brain checkouts until their shared theme includes Ears.

Green means no attention items/unknowns/source gaps in fresh observed data.
Yellow means attention or incomplete evidence; grey means no readable public
sources; stale means observation time expired. This is listening status, not
Heart release readiness or a community-health score. Empty coverage is grey.
Each item offers a public source link and portable community-triage prompt.
Clipboard failure exposes selectable prompt text; external text is escaped.

## Operation

Python 3.12+ and PyYAML; `gh` for live reads. GitHub Actions supplies its
read-only token. Local operators use their existing GitHub authentication;
never add credentials to config. No model/API calls or billing path.
GraphQL unavailability on a particular token or proxy is reported as partial
coverage; it never triggers credential changes or a write request. GraphQL
queries use HTTP POST as required by that read API, but contain no mutations.

```bash
python bin/pyauto-ears scan --mind ../PyAutoMind --output output/snapshot.json
python bin/pyauto-ears check --snapshot output/snapshot.json
python bin/pyauto-ears board --snapshot output/snapshot.json --brain ../PyAutoBrain --output _site
python ../PyAutoBrain/board/_state.py _site/state.json
python -m pytest -q
```

Pages builds on main, manual dispatch and every two hours. Set repository
Pages source to GitHub Actions before first deployment. PR CI never deploys.
Deployment failure is not fixed by publishing fabricated data. No scheduled
agent session is created. The workflow is ordinary repository automation.
