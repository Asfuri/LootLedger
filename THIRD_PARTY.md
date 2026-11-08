# Third-party code

LootLedger is MIT licensed (see LICENSE). Fortnite and its trademarks belong to Epic Games; this project is independent and not endorsed by Epic. LootLedger reads replay files that Fortnite saves locally and bundles no game assets.

**Slint** (SixtyFPS GmbH) draws the interface. It is used under the [Slint Royalty-free Desktop, Mobile, and Web Applications License 2.0](https://slint.dev/terms-and-conditions#royalty-free), with the attribution in the README. [Made with Slint](https://slint.dev).

**FortniteReplayDecompressor** (Shiqan and contributors), MIT, https://github.com/Shiqan/FortniteReplayDecompressor (commit `76f74c1`). The replay reader in `crates/core` (`bits.rs`, `replay.rs`, `tables.rs`) is a Rust port of its Unreal replay parsing and keeps its behaviour on purpose.

```
MIT License

Copyright (c) 2020-2026 Shiqan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Material Symbols** icon font (Google), Apache-2.0, https://github.com/google/material-design-icons. A subset ships as `crates/app/ui/icons.ttf`, with the licence in `crates/app/ui/LICENSE-MaterialSymbols.txt`.

**Rust crates** (MIT or MIT/Apache-2.0): oozextract (Oodle decompression), aes, sha2, rusqlite with SQLite (public domain), serde, serde_json, chrono, uuid, csv, thiserror, png, rfd, raw-window-handle, embed-resource and the `windows` crate. `cargo tree` lists the full set.
