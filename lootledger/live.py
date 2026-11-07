"""Live match state from files on disk only: the replay Fortnite is writing, and its log file's timestamp.

Nothing here touches the Fortnite process. States: idle (Fortnite not running), waiting (running, no match
being recorded), live (a replay is being recorded), saving (the replay was just finished; LootLedger is
reading it) and ended (that match is counted).
"""
import math
import os
from pathlib import Path
import struct
import sys
import time
import wave

from .replay_reader import peek

FORTNITE_LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FortniteGame" / "Saved" / "Logs" / "FortniteGame.log"
STALE = 90  # Fortnite flushes the replay about every 20 s; no write for 90 s means recording stopped
RUNNING = 120  # the game writes its log continuously while it runs


def chime(folder, volume):
    """A short two-note chime at this volume (0–100). Written once per volume, played without blocking."""
    if sys.platform != "win32" or volume <= 0:
        return
    import winsound
    path = Path(folder) / f"chime-{volume}.wav"
    if not path.exists():
        rate, frames = 22050, bytearray()
        for note in (880, 1320):
            for i in range(int(rate * .22)):
                t = i / rate
                frames += struct.pack("<h", int(32767 * volume / 100 * .5 * math.sin(2 * math.pi * note * t) * math.exp(-t * 14)))
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(bytes(frames))
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


class Tracker:
    def __init__(self, log=FORTNITE_LOG):
        self.log = Path(log)
        self.state, self.file, self.facts, self.size, self.started = "idle", None, None, None, None

    def poll(self, folder, now=None):
        """Update and return the state. Cheap: one directory listing, a stat, and a header read on change."""
        now = time.time() if now is None else now
        try:
            newest = max(Path(folder).glob("*.replay"), key=lambda p: p.stat().st_mtime, default=None)
            stat = newest.stat() if newest else None
        except OSError:
            newest = stat = None
        if newest and now - stat.st_mtime < STALE:
            if (newest, stat.st_size) != (self.file, self.size):
                self.facts, self.size = peek(newest), stat.st_size
            if self.facts and self.facts["live"]:
                if newest != self.file:
                    self.file, self.started = newest, stat.st_ctime  # Windows: creation time = recording start
                self.state = "live"
                return self.state
        if self.state in ("live", "saving") and self.file is not None:
            self.state = "saving"  # finished (or stopped); stays here until the import is done
            return self.state
        if self.state != "ended":
            try:
                running = now - self.log.stat().st_mtime < RUNNING
            except OSError:
                running = False
            self.state = "waiting" if running else "idle"
        return self.state

    def counted(self):
        """The finished replay was imported: show it as ended until the next match starts."""
        if self.state == "saving":
            self.state = "ended"

    def info(self, now=None):
        now = time.time() if now is None else now
        recorded = (self.facts or {}).get("recorded", 0)
        return {"state": self.state, "file": self.file.name if self.file else None,
                "elapsed": now - self.started if self.started and self.state == "live" else None,
                "recorded": recorded, "locked": bool((self.facts or {}).get("locked"))}
