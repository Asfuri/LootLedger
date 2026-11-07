"""Read-only diagnostic of one real recording's growth and key placeholder. Not the app watcher."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lootledger.replay_reader import peek  # noqa: E402


def header(path):
    with path.open("rb") as stream:
        data = stream.read(4096)
    version, = struct.unpack_from("<I", data, 4)
    position = 8
    if version >= 7:
        count, = struct.unpack_from("<I", data, position)
        position += 4 + 20 * count
    position += 12
    length, = struct.unpack_from("<i", data, position)
    position += 4 + abs(length) * (2 if length < 0 else 1)
    live, = struct.unpack_from("<I", data, position)
    position += 16
    encrypted, key_length = struct.unpack_from("<II", data, position)
    key = data[position + 8:position + 8 + key_length]
    return {"live": bool(live), "encrypted": bool(encrypted), "key_bytes": key_length,
            "key_all_zero": bool(key) and not any(key)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    samples, started = [], time.monotonic()
    print(f"Sampling one replay for {args.seconds:g}s (headers only).", flush=True)
    while True:
        try:
            facts = peek(args.replay)
            meta = args.replay.stat()
            samples.append({"utc": datetime.now(timezone.utc).isoformat(), "elapsed": round(time.monotonic() - started, 3),
                            "bytes": meta.st_size, "mtime": meta.st_mtime, **header(args.replay),
                            "recorded_seconds": facts["recorded"] if facts else None,
                            "complete_chunks": facts["chunks"] if facts else None})
        except (OSError, ValueError, struct.error) as error:
            samples.append({"elapsed": round(time.monotonic() - started, 3), "error": type(error).__name__})
        if time.monotonic() - started >= args.seconds:
            break
        time.sleep(min(2, max(0.01, args.seconds - (time.monotonic() - started))))
    report = {"sample_interval_seconds": 2, "counts_decoded": False, "samples": samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(samples)} samples to {args.output}", flush=True)


if __name__ == "__main__":
    main()
