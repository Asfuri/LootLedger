"""Style guard: colours, radii and form controls come from the token and component layer only.

theme.py holds every colour and shape token; controls.py builds every form control. Anywhere else in the
app, a hex or rgb() colour, a literal border-radius or drawRoundedRect radius, or a raw Qt form control
(which would look like a default Windows control) fails this test. A line can opt out with
"# style-lint: allow (reason)" when the text is not styling, e.g. an example in an error message.
"""
from pathlib import Path
import re
import sys

PACKAGE = Path(__file__).resolve().parent.parent / "lootledger"
TOKEN_LAYER = {"theme.py", "controls.py"}
# Modules of the retired screen detector (not part of the interface) are not checked.
RETIRED = {"analyze.py", "calibration.py", "capture.py", "detector.py", "replay.py", "screenvision.py", "vision.py",
           "worker.py"}
RULES = {
    "hardcoded colour": re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?=[\"'])|\brgba?\("),
    "hardcoded radius": re.compile(r"border-radius:\s*\d|drawRoundedRect\(.*,\s*\d+(\.\d+)?\s*,\s*\d+(\.\d+)?\s*\)\s*$"),
    "native form control": re.compile(r"\bQ(ComboBox|SpinBox|DoubleSpinBox|DateEdit|TimeEdit|DateTimeEdit|Slider|"
                                      r"CheckBox|RadioButton|ToolTip)\b"),
}


def violations():
    found = []
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name in TOKEN_LAYER | RETIRED:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "style-lint: allow" in line:
                continue
            for rule, pattern in RULES.items():
                if pattern.search(line):
                    found.append(f"{path.name}:{number}: {rule}: {line.strip()[:100]}")
    return found


def test_styles_and_controls_come_from_the_token_layer():
    assert violations() == []


def test_the_guard_catches_each_kind_of_problem(tmp_path, monkeypatch):
    bad = tmp_path / "bad.py"
    bad.write_text('a = QColor("#ff0000")\nb = "border-radius: 6px"\nc = QSpinBox()\nd = "#e8b04f"  # style-lint: allow (x)\n',
                   encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "PACKAGE", tmp_path)
    assert [v.split(": ")[1] for v in violations()] == ["hardcoded colour", "hardcoded radius", "native form control"]
