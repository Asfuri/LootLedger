"""Run actual video decoding, native Windows OCR, CV and temporal fusion on artificial data."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lootledger.analyze import analyze
from lootledger.config import Config
from tests.synthetic import make_clip


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("local-data/synthetic"))
    args = parser.parse_args()
    video, config_path, _ = make_clip(args.output)
    report = analyze(video, Config.read(config_path), args.output / "report.json")
    print(f'Artificial video: {report["frames_analyzed"]} frames, {len(report["events"])} candidates')
    for event in report["events"]:
        print(f'{event["time"]:.3f}s: {event["status"]} — {event["reason"]}')
    print("No gameplay accuracy can be inferred. Automatic confirmation remains disabled.")
