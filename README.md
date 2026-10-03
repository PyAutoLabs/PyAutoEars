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

This bootstrap is awaiting integration: Brain's existing collector/cockpit
has not switched to Ears. Follow-through and recurring-theme synthesis are
subsequent phases in Mind's `community-organ-birth` epic. The `/feedback`
workflow is developed in Brain PR #454; standalone assistant rollout follows.

[Contract and operation](REFERENCE.md) · [Agent guidance](AGENTS.md)
