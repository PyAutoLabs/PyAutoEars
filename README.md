# PyAutoEars

The community listening organ of PyAutoLabs: public conversation evidence,
listening coverage and a dashboard showing who may need attention.

Users continue to ask questions, share feedback and discuss ideas on the
[PyAutoLabs Discussions hub](https://github.com/orgs/PyAutoLabs/discussions).
Ears never posts replies; Brain's Community workflow drafts them for approval.

## Run

With Python 3.12+, PyYAML, authenticated `gh`, and sibling Mind/Brain checkouts:

```bash
python bin/pyauto-ears board --mind ../PyAutoMind --brain ../PyAutoBrain --output _site
python -m pytest -q
```

The board publishes HTML, Markdown, source receipts and the shared cockpit
feed. Partial, unavailable and stale evidence is explicit; no raw transcripts
or private-source conversations are exported.

The [live listening board](https://pyautolabs.github.io/PyAutoEars/) publishes
Ears snapshots for Brain's Community adapter and a feed for the organ cockpit. Follow-through joins explicit maintainer evidence links through issues, PRs and
published releases, and flags contributor updates owed. See the contract for
`Delivery-*` links and conservative unknown states. Recurring-theme synthesis
remains a later phase. `/feedback` ships in Brain and all four domain assistants.

[Contract and operation](REFERENCE.md) · [Agent guidance](AGENTS.md)
