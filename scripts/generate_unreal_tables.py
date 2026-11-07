"""Generate the small hardcoded FName table from the existing MIT-licensed reader."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "replay-reader/vendor/FortniteReplayDecompressor/src/Unreal.Core/Models/Enums/UnrealNames.cs"
rows = [(int(value), name) for name, value in re.findall(r"^\s*(\w+)\s*=\s*(\d+)\s*[,}]", source.read_text(encoding="utf-8"), re.M)]
assert len(rows) > 100
assert len(set(index for index, _ in rows)) == len(rows)
text = "// Generated from the vendored UnrealNames.cs (MIT); run scripts/generate_unreal_tables.py.\n"
text += "pub const UNREAL_NAMES: &[(u32, &str)] = &[\n"
text += "".join(f'    ({index}, "{name}"),\n' for index, name in sorted(rows))
text += "];\n"

# Field tables of the replicated classes the chest attribution reads (all fields, so "unknown field"
# handling matches the old reader). Complex property types are opaque: consumed, never an error.
SIMPLE = {"PropertyBool": "Bool", "PropertyUInt32": "U32", "PropertyInt": "I32", "PropertyInt16": "I16",
          "PropertyUInt16": "U16", "PropertyByte": "Byte", "PropertyFloat": "F32", "PropertyDouble": "F64",
          "PropertyString": "Str", "PropertyNetId": "NetId", "PropertyObject": "Guid", "Enum": "Enum",
          "Ignore": "Skip", "PropertyVector": "Vector", "PropertyVector2D": "Vector2D",
          "PropertyVector10": "Packed(10, 24)", "PropertyVector100": "Packed(100, 30)",
          "PropertyVectorQ": "Packed(1, 24)", "PropertyRotator": "Rotator", "PropertyUInt64": "U64",
          "PropertyName": "Name", "RepMovement": "Opaque"}
PROPERTY = {"ActorGuid": "Guid", "NetworkGUID": "Guid", "ItemDefinition": "Guid", "FName": "Name", "FDateTime": "U64"}
ELEMENT = {**PROPERTY, "int": "I32", "float": "F32"}
del ELEMENT["FDateTime"]


def kind(layout, cs_type):
    cs_type = cs_type.rstrip("?")
    if layout in SIMPLE:
        return SIMPLE[layout]
    if layout == "Property":
        return PROPERTY.get(cs_type, "Opaque")
    if layout == "DynamicArray":
        element = ELEMENT.get(cs_type[:-2])
        return f"Array(Some(&Kind::{element}))" if element else "Array(None)"
    raise ValueError(layout)


models = ROOT / "replay-reader/vendor/FortniteReplayDecompressor/src/FortniteReplayReader/Models/NetFieldExports"
for cls, const in [("FortPlayerState", "PLAYER_STATE"), ("GameState", "GAME_STATE"), ("PlayerPawn", "PLAYER_PAWN")]:
    body = (models / f"{cls}.cs").read_text(encoding="utf-8-sig")
    body = body[body.index("[NetFieldExportGroup("):]
    fields = re.findall(r'\[NetFieldExport\("([^"]+)",\s*RepLayoutCmdType\.(\w+)[^\]]*\]\s*(?:\[[^\]]*\]\s*)*'
                        r'public\s+([\w<>\[\]?.]+)\s+\w+', body)
    assert len(fields) > 50, cls
    text += f"\npub const {const}: &[(&str, Kind)] = &[\n"
    text += "".join(f'    ("{name}", Kind::{kind(layout, cs_type)}),\n' for name, layout, cs_type in fields)
    text += "];\n"
text = text.replace("pub const UNREAL_NAMES", "use crate::replay::Kind;\n\npub const UNREAL_NAMES", 1)
(ROOT / "crates/core/src/tables.rs").write_text(text, encoding="utf-8")
print(f"Generated {len(rows)} FName constants and the field tables")
