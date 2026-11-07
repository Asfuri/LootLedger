"""Check LootLedger's replay counts against a known match, and check that the totals add up.

    python scripts/verify_replays.py                      # the bundled known match (no Fortnite files needed)
    python scripts/verify_replays.py <file.replay> ...    # also read real replays and check each one

Nothing is written. Exit code 1 when a check fails. Replays without a known answer are still checked for
internal consistency: your count equals your events, teammate totals equal their parts, and every
unattributed chest is counted once.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lootledger.replay_reader import analyze, classify, summarize  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "replay-squad.json"
# Known answer: the 17:23 squad match, counted by hand from the game (27 opened + 9 broken by you).
KNOWN_OWN = {"opened": 27, "broken": 9}
# What this version reads for the same match. A change here should be deliberate.
EXPECTED_TEAM = {"opened": 12, "broken": 5, "unattributed": 20}


def totals(counts):
    """Opened and broken sums over a {type: {opened, broken}} mapping."""
    return {kind: sum(c[kind] for c in counts.values()) for kind in ("opened", "broken")}


def check(result):
    """Return (row for the table, list of problems) for one helper result."""
    problems = []
    mine, meta = summarize(result)
    me = next(p for p in meta["players"] if p["me"])
    mates = [p for p in meta["players"] if not p["me"]]
    own = totals(me["counts"])
    team = {kind: sum(totals(p["counts"])[kind] for p in mates) for kind in ("opened", "broken")}
    if sum(own.values()) != len(mine):
        problems.append("your total does not equal your chest events")
    if team != totals(meta["team"]):
        problems.append("teammate totals do not equal the per-type breakdown")
    unknown = sum(1 for e in result.get("events", []) if e["by"] == "unknown" and classify(e["cls"])[1])
    if unknown != meta["unattributed"]:
        problems.append("unattributed count is wrong")
    row = {"mode": meta["mode"], "you": own, "teammates": team, "unattributed": meta["unattributed"]}
    return row, problems


def run_offline():
    result = json.loads(FIXTURE.read_text(encoding="utf-8"))
    row, problems = check(result)
    mine = [e for e in result["events"] if e["by"] == "me" and classify(e["cls"])[1]]
    own = {kind: sum(1 for e in mine if e["kind"] == kind) for kind in ("opened", "broken")}
    if own != KNOWN_OWN:
        problems.append(f"known match: you read {own}, expected {KNOWN_OWN}")
    if row["teammates"] != {kind: EXPECTED_TEAM[kind] for kind in ("opened", "broken")}:
        problems.append(f"known match: teammates read {row['teammates']}, expected {EXPECTED_TEAM}")
    if row["unattributed"] != EXPECTED_TEAM["unattributed"]:
        problems.append(f"known match: unattributed {row['unattributed']}, expected {EXPECTED_TEAM['unattributed']}")
    return [("known match (fixture)", row, problems)]


def run_files(paths):
    return [(Path(result["file"]).name, *check(result)) for result in analyze(paths)]


def main(argv):
    results = run_offline() + run_files(argv)
    failed = 0
    for name, row, problems in results:
        failed += bool(problems)
        status = "FAIL" if problems else "ok"
        print(f"[{status}] {name}: you {row['you']['opened']} opened / {row['you']['broken']} broken | "
              f"teammates {row['teammates']['opened']} opened / {row['teammates']['broken']} broken | "
              f"unattributed {row['unattributed']} | {row['mode']}")
        for problem in problems:
            print(f"       - {problem}")
    print(f"\n{len(results) - failed} of {len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
