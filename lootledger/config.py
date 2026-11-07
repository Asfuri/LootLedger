from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path


DETECTOR_REVISION = 8


def model_folder():
    return Path(__file__).resolve().parent / "assets"


def data_dir():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "LootLedger"


@dataclass
class Config:
    detector_backend: str = "model"
    language: str = "en-US"
    chest_label: str = "CHEST"
    search_label: str = "SEARCH"
    blocked_labels: list[str] = field(default_factory=lambda: [
        "SPECTATING", "SPECTATE", "RETURN TO LOBBY", "VICTORY ROYALE", "YOU PLACED"])
    # All regions use normalized client/display coordinates: x, y, width, height.
    regions: dict = field(default_factory=lambda: {
        "chest": [.32, .32, .36, .48],
        "search": [.43, .40, .25, .25],
        "progress": [.47, .44, .10, .14],
        "xp": [.55, .22, .28, .22],
        "hud": [.02, .90, .18, .06],
        "mode": [.20, .04, .60, .26],
    })
    templates: list[dict] = field(default_factory=list)
    capture: dict = field(default_factory=lambda: {"kind": "display", "index": 1})
    frame_size: list[int] = field(default_factory=list)
    progress_calibrated: bool = False
    match_threshold: float = .55
    confirm_threshold: float = .88
    review_threshold: float = .55
    type_margin: float = .07
    frame_hz: int = 10
    timeout: float = 5.0
    evidence: bool = False
    hotkey_add: str = "Ctrl+Alt+F8"
    hotkey_undo: str = "Ctrl+Alt+F9"
    validation_report: str = ""
    # Replay tracking (v0.4). An empty folder means Fortnite's default Demos folder.
    replay_folder: str = ""
    count_broken: bool = True
    scan_seconds: int = 20
    auto_watch: bool = True

    def validate(self):
        if self.detector_backend not in ("model", "template"):
            raise ValueError("Unknown detector backend")
        if not 2 <= self.frame_hz <= 30 or not .5 <= self.timeout <= 30:
            raise ValueError("Frame rate must be 2–30 and timeout 0.5–30 seconds")
        if not 0 <= self.review_threshold <= self.confirm_threshold <= 1:
            raise ValueError("Require 0 ≤ review threshold ≤ confirmation threshold ≤ 1")
        if not .5 <= self.match_threshold <= 1 or not 0 <= self.type_margin <= 1:
            raise ValueError("Invalid template threshold or type margin")
        for name in ("chest", "search", "progress", "xp", "hud", "mode"):
            x, y, w, h = self.regions[name]
            if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1.00001 or y + h > 1.00001:
                raise ValueError(f"Invalid {name} region")
        if not self.chest_label.strip() or not self.search_label.strip():
            raise ValueError("Exact chest and search labels are required")
        if not 5 <= self.scan_seconds <= 600:
            raise ValueError("Replay check interval must be 5–600 seconds")

    def fingerprint(self):
        payload = asdict(self)
        payload["detector_revision"] = DETECTOR_REVISION
        if self.detector_backend == "model":
            payload["model_files"] = {name: hashlib.sha256((model_folder() / name).read_bytes()).hexdigest()
                                      if (model_folder() / name).is_file() else "missing"
                                      for name in ("chest-state.onnx", "chest-anchors.npz", "chest-model.json")}
        for key in ("validation_report", "evidence", "hotkey_add", "hotkey_undo", "capture",
                    "replay_folder", "count_broken", "scan_seconds", "auto_watch"):
            payload.pop(key)
        for template in payload["templates"]:
            path = Path(template["path"])
            template["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def validated(self):
        try:
            report = json.loads(Path(self.validation_report).read_text(encoding="utf-8"))
            return (report["config_sha256"] == self.fingerprint()
                    and report["real_footage"] is True and report["release_gate"] is True)
        except (OSError, ValueError, KeyError):
            return False

    def calibration_errors(self):
        if self.detector_backend == "model":
            missing = [name for name in ("chest-state.onnx", "chest-anchors.npz", "chest-model.json")
                       if not (model_folder() / name).is_file()]
            return ["Detector files missing; reinstall the complete LootLedger folder"] if missing else []
        kinds = {t["state"] for t in self.templates if Path(t["path"]).is_file()}
        missing = {"closed", "opened", "hud"} - kinds
        return [f"Add {name} reference crop" for name in sorted(missing)] + (
            [] if self.frame_size else ["Save capture resolution"]) + (
            [] if self.progress_calibrated else ["Mark the interaction circle in Quick setup"])

    def save(self, path):
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        temp.replace(path)

    @classmethod
    def read(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else {}
        if payload and "detector_backend" not in payload:
            payload.update(detector_backend="model", match_threshold=.55)
        config = cls(**payload)
        config.validate()
        return config
