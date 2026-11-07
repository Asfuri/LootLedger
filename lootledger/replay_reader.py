"""Chest openings from Fortnite's local replay files.

Fortnite records a replay of every match (Settings > Game > Record Replays) in
%LOCALAPPDATA%\\FortniteGame\\Saved\\Demos. The bundled ``LootLedger.ReplayReader``
helper decodes a replay and reports, for every chest or container, who searched it
(``SearchingPawn`` in the game's replicated data). Nothing reads game memory or
network traffic: the files are the game's own recordings on this PC.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

HELPER = "LootLedger.ReplayReader.exe"
LIVE_WINDOW = 15 * 60  # A replay still marked "live" but untouched for longer was abandoned (crash/quit).

# Display names come from Fortnite's own class names; order matters (first match wins).
CHEST_TYPES = (
    (re.compile(r"RareChest", re.I), "Rare chest"),
    (re.compile(r"BuriedChest", re.I), "Buried chest"),
    (re.compile(r"SpritePosters|Booty_Chest", re.I), "Sprite poster chest"),
    (re.compile(r"Relic|Extraction", re.I), "Relic chest"),
    (re.compile(r"LootCannon", re.I), "Loot cannon chest"),
    (re.compile(r"Tiered_Chest|NormalChest|FactionChest", re.I), "Chest"),
    (re.compile(r"Chest", re.I), "Other chest"),
)
OTHER_CONTAINERS = (
    (re.compile(r"Ammo", re.I), "Ammo box"),
    (re.compile(r"FoodBox", re.I), "Food box"),
    (re.compile(r"Fishing", re.I), "Fishing barrel"),
)


def classify(unreal_class):
    """Return (display name, counts as a chest)."""
    for pattern, name in OTHER_CONTAINERS:
        if pattern.search(unreal_class):
            return name, False
    for pattern, name in CHEST_TYPES:
        if pattern.search(unreal_class):
            return name, True
    return "Other container", False


def default_folder():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FortniteGame" / "Saved" / "Demos"


def helper_path():
    candidates = []
    if getattr(sys, "frozen", False):
        candidates += [Path(getattr(sys, "_MEIPASS", "")) / "replay-reader" / HELPER,
                       Path(sys.executable).resolve().parent / "replay-reader" / HELPER]
    root = Path(__file__).resolve().parent.parent / "replay-reader"
    candidates += [root / "publish" / HELPER, *sorted(root.glob(f"bin/Release/*/*/{HELPER}")),
                   *sorted(root.glob(f"bin/Release/*/{HELPER}"))]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("The replay reader is missing. Reinstall the complete LootLedger folder.")


def analyze(paths, helper=None, timeout=900):
    """Run the helper on replay files; returns one result dict per path, in order."""
    paths = [str(p) for p in paths]
    if not paths:
        return []
    command = [str(helper or helper_path()), *paths]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    done = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=flags)
    if done.returncode != 0:
        raise RuntimeError("Replay reader failed: " + done.stderr.decode("utf-8", "replace").strip()[-400:])
    results = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines() if line.strip()]
    if len(results) != len(paths):
        raise RuntimeError(f"Replay reader returned {len(results)} results for {len(paths)} files")
    return results


def started_at(result, mtime):
    """Match start as an aware UTC datetime (replays store local clock time)."""
    if result.get("timestamp"):
        try:
            return datetime.fromisoformat(result["timestamp"]).astimezone().astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime, timezone.utc) - timedelta(seconds=result.get("lengthSeconds") or 0)


def player_key(epic, name):
    """Stable id for one player. The Epic id is hashed, so exports never carry the raw account id."""
    if epic:
        return "epic-" + hashlib.sha256(epic.encode("utf-8")).hexdigest()[:16]
    return f"name-{name}" if name else None


def summarize(result):
    """Split a helper result into your chest openings and match metadata.

    ``meta["players"]`` lists you and each teammate the replay showed, you first. Each has a stable ``key``,
    ``counts`` per chest type as ``{"opened": n, "broken": n}``, and ``containers`` (ammo boxes and so on).
    ``meta["unattributed"]`` counts chests whose searcher the replay never recorded.
    """
    owner = result.get("owner") or {}
    me = player_key(owner.get("epicId"), owner.get("name")) or "me"
    mine, containers, team, teammates, players = [], {}, {}, {}, {}

    def seat(key, name, team_index, bot=False):
        if key not in players:
            players[key] = {"key": key, "name": name or "Teammate", "me": key == me, "bot": bool(bot),
                            "team": team_index, "counts": {}, "containers": {}}
        return players[key]

    seat(me, owner.get("name"), owner.get("team"))
    for mate in result.get("teammates", []):
        key = player_key(mate.get("epicId"), mate.get("name"))
        if key:
            seat(key, mate.get("name"), mate.get("team"), mate.get("bot"))
    unattributed = 0
    for event in result.get("events", []):
        name, is_chest = classify(event["cls"])
        if event["by"] == "unknown":
            unattributed += is_chest  # opened before your game first showed it: no searcher to credit
            continue
        if event["by"] not in ("me", "team"):
            continue
        if event["by"] == "me":
            person = players[me]
            if is_chest:
                mine.append({**event, "type": name})
            else:
                containers[name] = containers.get(name, 0) + 1
        else:
            person = seat(player_key(event.get("playerId"), event.get("player")) or f"anon-{event.get('pawn')}",
                          event.get("player"), None)
            if is_chest:
                counts = team.setdefault(name, {"opened": 0, "broken": 0})
                counts[event["kind"]] = counts.get(event["kind"], 0) + 1
                player = event.get("player") or "Teammate"
                teammates[player] = teammates.get(player, 0) + 1
        if is_chest:
            counts = person["counts"].setdefault(name, {"opened": 0, "broken": 0})
            counts[event["kind"]] += 1
        else:
            person["containers"][name] = person["containers"].get(name, 0) + 1

    def total(person):
        return sum(c["opened"] + c["broken"] for c in person["counts"].values())

    ordered = sorted(players.values(), key=lambda p: (not p["me"], -total(p), p["name"]))
    meta = {
        "file": Path(result["file"]).name, "playlist": result.get("playlist"), "mode": mode_name(result.get("playlist")),
        "placement": result.get("placement"), "total_players": result.get("totalPlayers"),
        "eliminations": result.get("eliminations"), "length": result.get("lengthSeconds"),
        "owner": owner.get("name"), "owner_id": owner.get("epicId"),
        "teammates": [t.get("name") for t in result.get("teammates", []) if t.get("name")],
        "containers": containers, "team": team, "team_players": teammates,
        "complete": bool(result.get("ok")), "error": result.get("error"), "branch": result.get("branch"),
        "players": ordered, "unattributed": unattributed,
    }
    return mine, meta


def mode_name(playlist):
    """Readable Battle Royale mode; other playlists keep their own name."""
    if not playlist:
        return "Unknown mode"
    text = playlist.lower()
    if not re.match(r"playlist_(default|nobuildbr|trios|habanero)", text):
        return re.sub(r"(?i)^playlist_", "", playlist)
    team = next((name for key, name in (("solo", "Solo"), ("duo", "Duo"), ("trio", "Trio"), ("squad", "Squad"))
                 if key in text), "")
    ranked = "Ranked " if "habanero" in text else ""  # Habanero is Fortnite's ranked playlist codename.
    return f"{ranked}{'Zero Build' if 'nobuild' in text else 'Build'} {team}".strip()


def match_key(result):
    owner = (result.get("owner") or {}).get("epicId") or "unknown"
    session = result.get("sessionId")
    return f"{session}:{owner}" if session else f"file:{Path(result['file']).name}"


def has_containers(result):
    return bool(result.get("events"))


def is_live(result, mtime, now):
    return bool(result.get("live")) and now - mtime < LIVE_WINDOW


def peek(path):
    """Header facts of a local replay without decoding it, or None if it can't be read (yet).

    Returns live (still recording), locked (encrypted and the key not written yet: Unreal writes the key
    only when the replay is finalized), recorded (end of the last complete data chunk, seconds) and chunks.
    """
    try:
        with open(path, "rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            head = handle.read(4096)
            pos = 0

            def u32():
                nonlocal pos
                value = struct.unpack_from("<I", head, pos)[0]
                pos += 4
                return value

            if u32() != 0x1CA2E27F:
                return None
            version = u32()
            if version >= 7:  # custom versions: a count, then 20 bytes each
                count = u32()
                pos += count * 20
            u32(), u32(), u32()  # length, network version, changelist
            name = struct.unpack_from("<i", head, pos)[0]
            pos += 4 + (name if name >= 0 else -name * 2)
            live = u32()
            pos += 8  # timestamp
            u32()  # compressed
            encrypted = u32()
            key = u32()
            pos += key
            recorded, chunks = 0, 0
            while pos + 16 <= size:
                handle.seek(pos)
                kind, length, start, end = struct.unpack("<IiII", handle.read(16))
                if length <= 0 or pos + 8 + length > size:
                    break  # a chunk still being written
                if kind == 1:
                    recorded = max(recorded, end)
                chunks += 1
                pos += 8 + length
    except (OSError, struct.error):
        return None
    return {"live": bool(live), "locked": bool(encrypted) and key == 0, "recorded": recorded / 1000, "chunks": chunks}


def scan(store, folder, *, helper=None, now=None, batch=12, progress=None, analyzer=analyze):
    """Import new or changed replays. Returns the newest in-progress replay result, if any.

    Imports are idempotent (deterministic ids), so a renamed copy or a re-scan never double counts.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Replay folder not found: {folder}")
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    known = store.replay_files()
    older = store.files_without_players()  # read before per-player details existed: read them again
    files, live = [], None
    for path in sorted(folder.glob("*.replay"), key=lambda p: p.stat().st_mtime):
        stat = path.stat()
        if path.name in older or known.get(path.name) != (stat.st_size, stat.st_mtime):
            facts = peek(path)
            if facts and facts["live"] and facts["locked"] and now - stat.st_mtime < LIVE_WINDOW:
                # Still recording and encrypted without its key: nothing can be decoded until Fortnite finishes it.
                live = {"file": str(path), "live": True, "locked": True, "events": [], "lengthSeconds": facts["recorded"]}
                continue
            files.append((path, stat))
    for start in range(0, len(files), batch):
        chunk = files[start:start + batch]
        for (path, stat), result in zip(chunk, analyzer([p for p, _ in chunk], helper=helper)):
            if is_live(result, stat.st_mtime, now):
                live = result
                continue
            store.import_replay(result, path.name, stat.st_size, stat.st_mtime)
        if progress:
            progress(min(start + batch, len(files)), len(files))
    return live
