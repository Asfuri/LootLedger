"""Temporal fusion only. Scores are evidence heuristics, not probabilities."""
from dataclasses import dataclass, field
from collections import deque
import math
import uuid


@dataclass
class Target:
    key: int
    closed: float = 0
    opened: float = 0
    chest_type: str = "Unknown"
    uncertain: bool = False


@dataclass
class Observation:
    time: float
    active: bool
    targets: list[Target] = field(default_factory=list)
    search: bool = False
    progress: float | None = None
    xp_tokens: list[str] = field(default_factory=list)
    text: dict = field(default_factory=dict)
    focus: int | None = None


@dataclass
class Event:
    id: str
    time: float
    status: str
    chest_type: str
    confidence: float
    reason: str
    target: int


@dataclass
class Interaction:
    key: int
    started: float
    last_seen: float
    closed_hits: int = 0
    opened_hits: int = 0
    opened_window: float | None = None
    opened_samples: int = 0
    opened_last: float | None = None
    searched: bool = False
    last_search: float | None = None
    low_progress: bool = False
    progressed: bool = False
    max_progress: float = 0
    progress_seen: bool = False
    opened_at: float | None = None
    ended_at: float | None = None
    uncertain: bool = False
    xp: bool = False
    emitted: bool = False
    chest_type: str = "Unknown"
    scores: list = field(default_factory=list)
    cancelled_frames: int = 0


class Detector:
    def __init__(self, config):
        self.config = config
        self.tracks = {}
        self.used_xp = set()
        self.seen_xp = set()
        self.recent_xp = deque()
        self.previous_time = None

    def reset(self):
        self.tracks.clear()
        self.used_xp.clear()
        self.seen_xp.clear()
        self.recent_xp.clear()
        self.previous_time = None

    def feed(self, obs):
        if not math.isfinite(obs.time) or (self.previous_time is not None and obs.time < self.previous_time):
            raise ValueError("Frames must have finite, ordered timestamps")
        if not obs.active:
            self.reset()
            return []
        if self.previous_time is not None and obs.time - self.previous_time > 1:
            self.reset()  # A capture stall cannot establish a continuous interaction.
        previous_time = self.previous_time
        self.previous_time = obs.time
        threshold = self.config.match_threshold
        for target in obs.targets:
            if target.key not in self.tracks and target.closed >= threshold:
                self.tracks[target.key] = Interaction(target.key, obs.time, obs.time)
            track = self.tracks.get(target.key)
            if track is None or track.emitted:
                continue
            if target.uncertain:
                track.uncertain = True
            track.last_seen = obs.time
            if target.closed >= threshold and track.opened_at is None:
                track.closed_hits += 1
                track.scores.append(target.closed)
                if target.chest_type != "Unknown":
                    track.chest_type = target.chest_type
            elif not track.searched:
                track.closed_hits = 0
            if track.searched and target.closed >= threshold and not (obs.search and obs.focus == target.key):
                track.cancelled_frames += 1
                if track.cancelled_frames >= 2:
                    track.uncertain = True
                    # Brief OCR misses are not proof that an interaction stopped.
                    if not (track.progressed and track.max_progress >= .8) and obs.time - track.last_search >= .35:
                        track.searched = track.low_progress = track.progressed = False
                        track.max_progress = 0
                        track.progress_seen = False
                        track.opened_window, track.opened_samples, track.opened_last = None, 0, None
                        track.ended_at, track.xp = None, False
            else:
                track.cancelled_frames = 0
            # Search belongs to the closest crosshair target selected by perception.
            if obs.search and target.key == obs.focus and target.closed >= threshold:
                track.last_search = obs.time
                track.searched = track.searched or track.closed_hits >= 2
                if obs.progress is not None:
                    if obs.progress < track.max_progress - .4:
                        if not (track.progressed and track.max_progress >= .8):
                            track.low_progress, track.progressed, track.max_progress = False, False, 0
                            track.progress_seen = False
                            track.ended_at, track.xp = None, False
                            track.opened_window, track.opened_samples, track.opened_last = None, 0, None
                    if obs.progress <= .5:
                        track.low_progress = True
                    if track.low_progress and track.progress_seen and obs.progress >= track.max_progress + .12:
                        track.progressed = True
                    track.max_progress = max(track.max_progress, obs.progress)
                    track.progress_seen = True
            if target.opened >= threshold and track.searched and not (obs.search and obs.focus == target.key):
                track.opened_hits = track.opened_hits + 1 if track.opened_last == previous_time else 1
                track.opened_last = obs.time
                if track.opened_window is None or obs.time - track.opened_window > .8:
                    track.opened_window, track.opened_samples = obs.time, 0
                track.opened_samples += 1
                track.scores.append(target.opened)
                if track.opened_samples >= 2 and track.opened_at is None:
                    track.opened_at = obs.time
                    if track.opened_hits < 2:
                        track.uncertain = True
            elif track.opened_at is None:
                track.opened_hits = 0

        for key, track in self.tracks.items():
            if track.searched and not track.emitted:
                if obs.search and obs.focus == key:
                    track.ended_at = None
                elif track.ended_at is None:
                    track.ended_at = obs.time

        for token in obs.xp_tokens:
            if token not in self.seen_xp:
                self.recent_xp.append((obs.time, token))
                self.seen_xp.add(token)
        while self.recent_xp and obs.time - self.recent_xp[0][0] > self.config.timeout:
            self.recent_xp.popleft()
        # Bind fresh XP to one completed personal interaction; overlapping candidates stay uncertain.
        for stamp, token in list(self.recent_xp):
            eligible = [t for t in self.tracks.values() if t.searched and not t.emitted
                        and not t.xp and t.started <= stamp and stamp - t.started <= self.config.timeout
                        and (t.opened_at is not None or (t.ended_at is not None and t.progressed and t.max_progress >= .8))
                        and (t.ended_at is None or stamp >= t.ended_at - .25)
                        and abs((t.opened_at if t.opened_at is not None else t.ended_at) - stamp) <= 2]
            if len(eligible) == 1:
                eligible[0].xp = True
                self.used_xp.add(token)
                self.recent_xp.remove((stamp, token))

        events = []
        for key, track in list(self.tracks.items()):
            if track.emitted:
                # Retain event identity while the object is still observed.
                if not any(t.key == key for t in obs.targets) and obs.time - track.last_seen > 8:
                    del self.tracks[key]
                else:
                    if any(t.key == key for t in obs.targets):
                        track.last_seen = obs.time
                continue
            complete = track.opened_at is not None
            timed_out = obs.time - track.started > self.config.timeout
            if complete and track.xp:
                strong = track.closed_hits >= 2 and track.progressed and track.max_progress >= .85 and not track.uncertain
                confidence = min(track.scores) if strong else .65
                status = "confirmed" if strong and confidence >= self.config.confirm_threshold else "review"
                reason = "Closed → search progress → opened; fresh CHEST XP" if strong else "Opened + CHEST XP; progress incomplete"
                if track.uncertain:
                    reason = "Opening sequence needs review: chest identity or interaction completion uncertain"
            elif track.xp and track.ended_at is not None and obs.time - track.ended_at >= .6:
                confidence, status = .6, "review"
                reason = "Closed chest + near-complete search + fresh CHEST XP; opened state not established"
            elif timed_out and complete:
                confidence, status, reason = .6, "review", "Opened after search; chest XP missing or ambiguous"
            elif timed_out:
                del self.tracks[key]  # Cancellation or camera loss alone is not an opening.
                continue
            else:
                continue
            if confidence >= self.config.review_threshold:
                stamp = track.ended_at if track.ended_at is not None else track.opened_at
                events.append(Event(str(uuid.uuid4()), obs.time if stamp is None else stamp,
                                    status, track.chest_type, confidence, reason, key))
            track.emitted = True
        return events

    def finish(self):
        """Keep observed completions reviewable when a clip ends before XP arrives."""
        pending = [Event(str(uuid.uuid4()), t.ended_at if t.ended_at is not None else t.opened_at, "review", t.chest_type, .6,
                         "Clip ended after opened state; confirmation incomplete" if t.opened_at is not None else
                         "Full search and chest XP observed; opened state not established", t.key)
                   for t in self.tracks.values() if (t.opened_at is not None or (t.ended_at is not None and t.xp)) and not t.emitted
                   and self.config.review_threshold <= .6]
        self.reset()
        return pending
