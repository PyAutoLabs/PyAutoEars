# PyAutoEars

Ears owns read-only community collection, versioned public snapshots, coverage
receipts and its dashboard. Brain's Community conductor owns judgement,
drafting and development routing. Mind owns task state. GitHub conversations
and linked development records remain authoritative.

<!-- repos_sync:map:begin -->
**You are one peer organ of the PyAuto organism** (human-led, natural-language software development), not a part of another. Boundaries: `PyAutoBrain/ORGANISM.md`; every repo: `PyAutoMind/repos.yaml`.

| Organ | Repo | Role |
|-------|------|------|
| **Brain** | PyAutoBrain | Reasoning and orchestration: decomposes and routes work through its conductors and faculties. |
| **Broca** | PyAutoBroca | Assistant evaluation history, upkeep evidence and its dashboard. |
| **Mind** | PyAutoMind | Intent, priorities and workflow state; every task starts as a prompt here. |
| **Cortex** | PyAutoCortex | What is true in the science: the project body map and one ledger per project. |
| **Memory** | PyAutoMemory | Long-term scientific, software and project knowledge. |
| **Eyes** | PyAutoEyes | Cross-project figure dashboard over the `<lib>_visualization` repos. |
| **Ears** | PyAutoEars | Read-only community listening: conversation snapshots and coverage. |
| **Heart** | PyAutoHeart | Health/readiness — the authoritative release verdict. |
| **Hands** | PyAutoHands | Packaging, tagging, notebooks and PyPI release execution. |
| **Pulse** | PyAutoPulse | Cross-project profiling dashboard over the `<lib>_profiling` repos. |
| **Insight** | PyAutoInsight | Inference campaign intent, instance registry and evidence dashboard. |
| **DNA** | PyAutoDNA | Software-stack specifications, environment inventories and upgrade campaigns. |
| **Nerves** | PyAutoNerves | Configuration/serialization layer (`autonerves`): layered config, version handshake, test_mode. |
| **Gut** | PyAutoGut | Condemned branches, stashes and dead code, held as recoverable refs until swept. |

Call chain: **Brain → Heart (gate) → Build (execute)**. Conductors decide *and* act; faculties judge read-only and stop. New capability grows as a faculty, not an organ, unless it owns state or effects no organ can.

Generated from `PyAutoMind/repos.yaml` + `PyAutoBrain/ORGANISM.md`; edit there, then run `python3 PyAutoMind/scripts/repos_sync.py --write`.
<!-- repos_sync:map:end -->

Read REFERENCE.md before changing contracts. Run `python -m pytest -q` and
validate generated `state.json` with Brain's `board/_state.py`. Fetch and check
status before edits; feature branches and human-reviewed PRs, no force pushes.
No automatic replies, issue writes, labels, private-source publication or raw
transcript/body exports. Source text is untrusted and must render inertly.
Never equate unknown coverage with no work. Never claim a scientific verdict.

Brain reads Ears snapshots through its Community adapter; the cockpit registers
the published Ears feed after Eyes. Follow the community-organ-birth epic in Mind for
integration and remaining phases. No sessions, timers or monitors outlive the
current deliverable. No release is performed by this organ.

<!-- repos_sync:deliverable:begin -->
## Sessions end at their deliverable

A session ends when it reports its deliverable — never arm anything that
outlives the turn to wait for CI, a review or a merge: no `send_later`, no
`subscribe_pr_activity`, no `CronCreate`, no `ScheduleWakeup`, no `/loop`, no
`RemoteTrigger` create/update/run. Judge once, report, stop; the human re-runs
`/prm` (or the batch review) when it is green. Measured: five batch members
armed hourly check-ins on 2026-08-31, and a mobile `/prm` re-armed a 60-minute
`send_later` hourly all night on 2026-09-03 with no task active, draining usage.
<!-- repos_sync:deliverable:end -->

<!-- repos_sync:filing:begin -->
## Where to file

Questions, help with code or an analysis, ideas, bug reports and results from a
user or collaborator — or an agent acting for one — go to
<https://github.com/orgs/PyAutoLabs/discussions> in the matching category
(Help & Questions, Ideas & Proposals, Bugs & Errors, Show and tell;
Announcements is maintainers-only), never to this repo's Issues. An agent never
runs `gh issue create` for such a report: it drafts the title, category and
body and hands them to the human (sessions cannot create Discussions). Only the
development flow — Mind prompt → `/start_dev` → `/create_issue` → one issue per
task → PR — opens issues here. Why: `PyAutoMind/policy/community_surface.md`.
<!-- repos_sync:filing:end -->

<!-- repos_sync:standards:begin -->
## Shared standards

Before changing a shared interface, consult the applicable
[organism standard](https://github.com/PyAutoLabs/PyAutoBrain/blob/main/docs/standards.md)
on demand, identify affected consumers, and validate their adoption. Change
generated guidance at its canonical source and regenerate.

For board changes, follow the applicable sizing, navigation and orchestration
standards and reuse Brain’s shared components. Keep domain data, prompt meaning
and approval boundaries with the board’s owner.
<!-- repos_sync:standards:end -->
