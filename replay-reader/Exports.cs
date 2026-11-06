using Unreal.Core.Attributes;
using Unreal.Core.Contracts;
using Unreal.Core.Models.Enums;

namespace LootLedger.ReplayReader;

/// <summary>
/// Parses every searchable container class (chests, rare/relic/buried chests, ammo boxes...).
/// Paths are aliased to this class at runtime; see <see cref="ChestReplayReader"/>.
/// Nullable fields stay null unless the replay updated them in this export.
/// </summary>
[NetFieldExportGroup(Path, minimalParseMode: ParseMode.Minimal)]
public class SearchableContainer : INetFieldExportGroup
{
    public const string Path = "LootLedger/SearchableContainer";

    [NetFieldExport("bAlreadySearched", RepLayoutCmdType.PropertyBool)]
    public bool? bAlreadySearched { get; set; }

    [NetFieldExport("bDestroyed", RepLayoutCmdType.PropertyBool)]
    public bool? bDestroyed { get; set; }

    [NetFieldExport("SearchingPawn", RepLayoutCmdType.PropertyObject)]
    public uint? SearchingPawn { get; set; }

    [NetFieldExport("SearchAnimationCount", RepLayoutCmdType.PropertyUInt32)]
    public uint? SearchAnimationCount { get; set; }
}

/// <summary>Any pawn class (bots, NPCs, mode-specific pawns) that the vendored reader does not parse.</summary>
[NetFieldExportGroup(Path, minimalParseMode: ParseMode.Minimal)]
public class AnyPawn : INetFieldExportGroup
{
    public const string Path = "LootLedger/AnyPawn";

    [NetFieldExport("PlayerState", RepLayoutCmdType.PropertyObject)]
    public uint? PlayerState { get; set; }
}
