using System.Globalization;
using System.Text.RegularExpressions;
using FortniteReplayReader.Models;
using FortniteReplayReader.Models.NetFieldExports;
using Unreal.Core.Contracts;
using Unreal.Core.Models.Enums;

namespace LootLedger.ReplayReader;

/// <summary>
/// Reads a Fortnite replay and reports who searched or broke each container.
///
/// Containers replicate <c>SearchingPawn</c> (set when an interaction starts),
/// <c>bAlreadySearched</c> (set when the search completes) and <c>bDestroyed</c>.
/// A pawn maps to a player state, and the replay names the recording player's state,
/// so each opening is attributed to the replay owner, a teammate, or someone else.
/// </summary>
public sealed class ChestReplayReader : FortniteReplayReader.ReplayReader
{
    // Unreal class paths only (RPC function groups contain ':'), ending in the generated class suffix.
    static readonly Regex ContainerClass = new(@"^[^:]*(?i:chest|ammo|/containers/|booty|lootcannon)[^:]*_C$", RegexOptions.Compiled);
    static readonly Regex PawnClass = new(@"^[^:]*(?i:pawn)[^:/]*_C$", RegexOptions.Compiled);
    static readonly Regex ClassName = new(@"[^./]+$", RegexOptions.Compiled);

    sealed class Container
    {
        public required string Cls;
        public uint? Pawn;
        public uint Animations;
        public Episode? Current;
        public bool Searched;
        public bool Destroyed;
        public readonly List<Episode> Episodes = new();
    }

    sealed class Episode
    {
        public required double T;
        public required string Kind;
        public uint? Pawn;
    }

    readonly Dictionary<uint, Container> _containers = new();
    readonly Dictionary<uint, uint> _pawnToState = new();
    readonly Dictionary<uint, (string? Epic, int? Team, bool? Bot)> _states = new();
    readonly List<string>? _trace;
    uint? _recorder;
    string? _sessionId, _playlist;
    int? _teamSize;

    public ChestReplayReader(bool trace = false) : base(null, ParseMode.Normal)
    {
        _trace = trace ? new List<string>() : null;
        _netFieldParser.GroupFallback = path =>
            ContainerClass.IsMatch(path) ? SearchableContainer.Path :
            PawnClass.IsMatch(path) ? AnyPawn.Path : null;
    }

    public static ReplayResult Analyze(string path, bool trace = false)
    {
        var reader = new ChestReplayReader(trace);
        var result = new ReplayResult { File = path };
        FortniteReplay? replay = null;
        try
        {
            // Fortnite keeps the current match's replay open for writing; share access instead of locking it.
            byte[] bytes;
            using (var file = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            {
                bytes = new byte[file.Length];
                file.ReadExactly(bytes);
            }
            using var stream = new MemoryStream(bytes, writable: false);
            replay = reader.ReadReplay(stream);
            result.Ok = true;
        }
        catch (Exception error)
        {
            result.Ok = false;
            result.Error = $"{error.GetType().Name}: {error.Message}";
        }
        reader.Fill(result, replay);
        return result;
    }

    uint? ActorOf(uint channel) => Channels[channel]?.Actor?.ActorNetGUID.Value;

    protected override void OnExportRead(uint channelIndex, INetFieldExportGroup? exportGroup)
    {
        base.OnExportRead(channelIndex, exportGroup);
        if (ActorOf(channelIndex) is not { } actor)
        {
            return;
        }

        switch (exportGroup)
        {
            case SearchableContainer container:
                OnContainer(actor, container);
                break;
            case PlayerPawn pawn when pawn.PlayerState is { } state && state != 0:
                _pawnToState[actor] = state;
                break;
            case AnyPawn pawn when pawn.PlayerState is { } state && state != 0:
                _pawnToState[actor] = state;
                break;
            case FortPlayerState state:
                var old = _states.GetValueOrDefault(actor);
                _states[actor] = (state.UniqueId ?? state.UniqueID ?? old.Epic, state.TeamIndex ?? old.Team, state.bIsABot ?? old.Bot);
                break;
            case GameState game:
                if (game.RecorderPlayerState?.Value is { } recorder && recorder != 0)
                {
                    _recorder = recorder;
                }
                _sessionId ??= game.GameSessionId;
                _teamSize ??= game.TeamSize;
                break;
            case PlaylistInfo playlist:
                _playlist ??= playlist.Name;
                break;
        }
    }

    void OnContainer(uint actor, SearchableContainer update)
    {
        if (update.bAlreadySearched is null && update.bDestroyed is null && update.SearchingPawn is null && update.SearchAnimationCount is null)
        {
            return;
        }

        var cls = ClassName.Match(CurrentExportGroupPath ?? "").Value;
        if (!_containers.TryGetValue(actor, out var c))
        {
            _containers[actor] = c = new Container { Cls = cls };
        }

        _trace?.Add(string.Create(CultureInfo.InvariantCulture,
            $"{CurrentFrameTime:F2} a{actor} {cls} searched={update.bAlreadySearched} destroyed={update.bDestroyed} pawn={update.SearchingPawn} anim={update.SearchAnimationCount}"));

        if (update.bAlreadySearched == false)
        {
            // The container was reset (some modes respawn chests). A later search is a new opening.
            c.Current = null;
            c.Searched = false;
            c.Pawn = null;
        }
        if (update.SearchAnimationCount is { } animations)
        {
            c.Animations = animations;
        }
        if (update.SearchingPawn is { } pawn && pawn != 0)
        {
            // SearchingPawn is set when the interaction starts; it is cleared (0) when that pawn goes away.
            c.Pawn = pawn;
            if (c.Current is { Pawn: null } waiting)
            {
                waiting.Pawn = pawn;
            }
        }
        if (update.bAlreadySearched == true && !c.Searched)
        {
            c.Searched = true;
            c.Current = new Episode { T = CurrentFrameTime, Kind = "opened", Pawn = c.Pawn };
            c.Episodes.Add(c.Current);
        }
        if (update.bDestroyed == true && !c.Destroyed)
        {
            c.Destroyed = true;
            // Destroying a closed container spills its loot: SearchAnimationCount rises and SearchingPawn
            // names the player whose damage broke it. A pawn without a completed search animation is only a
            // cancelled interaction, so it is not attributed.
            if (!c.Searched && c.Pawn is not null && c.Animations > 0)
            {
                c.Current = new Episode { T = CurrentFrameTime, Kind = "broken", Pawn = c.Pawn };
                c.Episodes.Add(c.Current);
            }
        }
    }

    void Fill(ReplayResult result, FortniteReplay? replay)
    {
        var info = Replay?.Info;
        result.Live = info?.IsLive ?? false;
        // Local replays store the recording PC's local clock time (it matches the file name), not UTC.
        result.Timestamp = info is null || info.Timestamp == default ? null : DateTime.SpecifyKind(info.Timestamp, DateTimeKind.Unspecified);
        result.LengthSeconds = (info?.LengthInMs ?? 0) / 1000.0;
        result.Branch = Replay?.Header?.Branch;
        result.SessionId = replay?.GameData?.GameSessionId ?? _sessionId;
        result.Playlist = replay?.GameData?.CurrentPlaylist ?? _playlist;
        result.TeamSize = replay?.GameData?.TeamSize ?? _teamSize;
        result.Placement = replay?.TeamStats is { } team && team.Position > 0 ? (int)team.Position : null;
        result.TotalPlayers = replay?.TeamStats is { } total && total.TotalPlayers > 0 ? (int)total.TotalPlayers : null;
        result.Eliminations = replay?.Stats is { } stats ? (int)stats.Eliminations : null;
        result.Trace = _trace;

        var recorder = _recorder ?? replay?.GameData?.RecorderId;
        var owner = recorder is { } r ? _states.GetValueOrDefault(r) : default;
        var players = replay?.PlayerData?.ToList() ?? new List<PlayerData>();
        string? NameOf(string? epic) => epic is null ? null :
            players.FirstOrDefault(p => p.EpicId == epic || p.BotId == epic)?.PlayerName;

        if (recorder is not null)
        {
            var ownerData = players.FirstOrDefault(p => p.IsReplayOwner);
            result.Owner = new PlayerInfo
            {
                EpicId = owner.Epic ?? ownerData?.EpicId,
                Name = ownerData?.PlayerName ?? NameOf(owner.Epic),
                Team = owner.Team ?? ownerData?.TeamIndex,
            };
        }
        var myTeam = result.Owner?.Team;
        if (myTeam is not null)
        {
            result.Teammates = _states.Where(s => s.Key != recorder && s.Value.Team == myTeam)
                .Select(s => new PlayerInfo { EpicId = s.Value.Epic, Name = NameOf(s.Value.Epic), Team = s.Value.Team, Bot = s.Value.Bot })
                .ToList();
        }

        foreach (var (actor, container) in _containers)
        {
            for (var i = 0; i < container.Episodes.Count; i++)
            {
                var episode = container.Episodes[i];
                var (by, player) = Attribute(episode.Pawn, recorder, myTeam);
                result.Events.Add(new ContainerEvent
                {
                    T = Math.Round(episode.T, 2),
                    Cls = container.Cls,
                    Kind = episode.Kind,
                    By = by,
                    Player = by == "team" ? NameOf(player) : null,
                    PlayerId = by == "me" ? result.Owner?.EpicId : by == "team" ? player : null,
                    Pawn = episode.Pawn,
                    Actor = actor,
                    Episode = i,
                });
            }
        }
        result.Events.Sort((a, b) => a.T.CompareTo(b.T));
    }

    (string By, string? Epic) Attribute(uint? pawn, uint? recorder, int? myTeam)
    {
        if (pawn is null || !_pawnToState.TryGetValue(pawn.Value, out var state))
        {
            return ("unknown", null);
        }
        if (state == recorder)
        {
            return ("me", null);
        }
        var info = _states.GetValueOrDefault(state);
        return (myTeam is not null && info.Team == myTeam ? "team" : "other", info.Epic);
    }
}
