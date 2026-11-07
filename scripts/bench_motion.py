"""Run the same synthetic chart/reorder spike for either Rust renderer, in an isolated profile."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from bench_release import sample, tree


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lootledger-motion-") as temp:
        data = Path(temp) / "LootLedger"
        data.mkdir()
        (data / "config.json").write_text('{"auto_watch":false}', encoding="utf-8")
        raw = Path(temp) / "frames.json"
        start = time.perf_counter()
        process = subprocess.Popen([str(args.exe.resolve()), "--exercise", f"--frame-report={raw}", "--quit-after=6"],
                                   env={**os.environ, "LOCALAPPDATA": temp})
        peak = private = cpu = 0
        try:
            while process.poll() is None:
                if time.perf_counter() - start > 45:
                    raise TimeoutError("Motion spike did not exit")
                values = sample(tree(process.pid))
                peak = max(peak, values["working_set_bytes"])
                private = max(private, values["private_bytes"])
                cpu = max(cpu, values["cpu_seconds"])
                time.sleep(.1)
            if process.returncode:
                raise RuntimeError(f"Motion spike exited {process.returncode}")
            report = json.loads(raw.read_text(encoding="utf-8"))
            report.update(exe_bytes=args.exe.stat().st_size, wall_seconds=round(time.perf_counter() - start, 3),
                          sampled_peak_working_set_bytes=peak, sampled_peak_private_bytes=private, cpu_seconds_lower_bound=cpu,
                          sample_interval_ms=100)
            out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({k: v for k, v in report.items() if k != "redraw_events_ms"}, indent=2))
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                process.wait(timeout=10)


if __name__ == "__main__":
    main()
