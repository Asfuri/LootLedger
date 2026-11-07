"""Measure the existing standalone replay helper without touching the ledger."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import time

from bench_release import sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("helper", type=Path)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = []
    for _ in range(3):
        with tempfile.TemporaryFile() as output:
            started = time.perf_counter()
            process = subprocess.Popen([str(args.helper.resolve()), str(args.replay.resolve())],
                                       stdout=output, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
            peak = cpu = 0
            while process.poll() is None:
                values = sample({process.pid})
                peak = max(peak, values["working_set_bytes"])
                cpu = max(cpu, values["cpu_seconds"])
                time.sleep(.02)
            wall = time.perf_counter() - started
            _, error = process.communicate(timeout=10)
            if process.returncode:
                raise RuntimeError(error.decode("utf-8", "replace"))
            output.seek(0)
            result = json.load(output)
            if not result["ok"]:
                raise RuntimeError(result.get("error", "Parser failed"))
            runs.append({"wall_seconds": round(wall, 3), "cpu_seconds_lower_bound": cpu,
                         "cpu_percent_one_core_lower_bound": round(cpu / wall * 100, 2),
                         "peak_working_set_bytes_sampled": peak, "events": len(result["events"])})
    report = {"measured_utc": datetime.now(timezone.utc).isoformat(),
              "replay_bytes": args.replay.stat().st_size, "sample_interval_ms": 20, "runs": runs,
              "note": "CPU is a lower bound: the final up-to-20ms before process exit is not sampled. OS cache uncontrolled."}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
