# Vendored FortniteReplayDecompressor

- Upstream: https://github.com/Shiqan/FortniteReplayDecompressor (MIT, see `LICENSE`)
- Commit: `76f74c1f640069afdba71b6468e2f819327893c2` (2026-09-13)
- Included projects: `Unreal.Core`, `Unreal.Encryption`, `OozSharp`, `FortniteReplayReader`

LootLedger applies a small patch (`lootledger.patch`):

1. `ReplayReader.CurrentFrameTime` exposes the replay time of the frame being read.
2. `ReplayReader.CurrentExportGroupPath` exposes the class path behind each `OnExportRead` call.
3. `NetFieldParser.GroupFallback` and `KeyList.AddAlias` let one parser class read several
   Unreal classes, so newly added chest classes are parsed without a code change.
