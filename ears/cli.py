"""Checkout CLI. Output is written only to an explicit local destination."""
import argparse
import json
import sys
from pathlib import Path

from .board import render
from .presentation import recorded_plans
from .followthrough import pending_releases
from .collect import GitHub, collect, homes, repository, validate


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["scan", "board", "check"])
    p.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config.json")
    p.add_argument("--mind", type=Path)
    p.add_argument("--brain", type=Path)
    p.add_argument("--snapshot", type=Path, help="Read a previously collected snapshot; never a transcript")
    p.add_argument("--output", type=Path, help="Required for board; optional snapshot output for scan")
    a = p.parse_args(argv)
    try:
        config = json.loads(a.config.read_text())
        repository(config["repo"])
        repository(config["hub"])
        if not config["self_logins"] or not all(isinstance(x, str) and x for x in config["self_logins"]):
            raise ValueError("self_logins must name maintainers")
        if type(config["max_pages"]) is not int or not 1 <= config["max_pages"] <= 100:
            raise ValueError("max_pages must be 1..100")
        if type(config["fresh_hours"]) is not int or not 1 <= config["fresh_hours"] <= 168:
            raise ValueError("fresh_hours must be 1..168")
        if a.mode == "board" and (not a.brain or not a.output):
            raise ValueError("board needs --brain and --output")
        if a.mode == "check" and not a.snapshot:
            raise ValueError("check needs --snapshot")
        if a.snapshot:
            snapshot = validate(json.loads(a.snapshot.read_text()))
        elif a.mind:
            snapshot = validate(collect(GitHub(), homes(a.mind), config, pending_releases(a.mind)))
        else:
            raise ValueError("scan/board needs --mind or --snapshot")
        if a.mode == "check":
            print("snapshot: valid")
        elif a.mode == "scan":
            payload = json.dumps(snapshot, indent=2) + "\n"
            if a.output:
                a.output.parent.mkdir(parents=True, exist_ok=True)
                a.output.write_text(payload)
            else:
                print(payload, end="")
        else:
            surfaces = render(snapshot, config, a.brain, plans=recorded_plans(a.mind) if a.mind else ())
            a.output.mkdir(parents=True, exist_ok=True)
            for name, text in surfaces.items():
                (a.output / name).write_text(text)
            (a.output / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
            print(f"board: {a.output}")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ears: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
