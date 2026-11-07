namespace LootLedger.ReplayReader;

public sealed class ReplayResult
{
    public int Schema { get; set; } = 1;
    public string File { get; set; } = "";
    public bool Ok { get; set; }
    public string? Error { get; set; }
    public bool Live { get; set; }
    public string? Branch { get; set; }
    /// <summary>Recording start in the PC's local time (no offset).</summary>
    public DateTime? Timestamp { get; set; }
    public double LengthSeconds { get; set; }
    public string? SessionId { get; set; }
    public string? Playlist { get; set; }
    public int? TeamSize { get; set; }
    public PlayerInfo? Owner { get; set; }
    public List<PlayerInfo> Teammates { get; set; } = new();
    public int? Placement { get; set; }
    public int? TotalPlayers { get; set; }
    public int? Eliminations { get; set; }
    public List<ContainerEvent> Events { get; set; } = new();
    public List<string>? Trace { get; set; }
}

public sealed class PlayerInfo
{
    public string? Name { get; set; }
    public string? EpicId { get; set; }
    public int? Team { get; set; }
    public bool? Bot { get; set; }
}

public sealed class ContainerEvent
{
    /// <summary>Replay seconds when the container was first seen searched/broken.</summary>
    public double T { get; set; }
    /// <summary>Unreal class, e.g. Tiered_Chest_Athena_C.</summary>
    public string Cls { get; set; } = "";
    /// <summary>"opened" (searched) or "broken" (destroyed and its loot spilled).</summary>
    public string Kind { get; set; } = "";
    /// <summary>"me", "team", "other" or "unknown".</summary>
    public string By { get; set; } = "";
    public string? Player { get; set; }
    /// <summary>Epic account id (bot id for bots) of the searching player: set for "me" and "team" events.</summary>
    public string? PlayerId { get; set; }
    /// <summary>Network GUID of the searching pawn, when the replay recorded one.</summary>
    public uint? Pawn { get; set; }
    /// <summary>Network GUID of the container: stable within one match.</summary>
    public uint Actor { get; set; }
    /// <summary>Search episode on this container (chests can be reset and searched again).</summary>
    public int Episode { get; set; }
}
