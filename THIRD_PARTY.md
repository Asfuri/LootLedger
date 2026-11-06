# Dependencies

Application code: MIT, see LICENSE. Fortnite and its trademarks belong to Epic Games; this project is independent and not endorsed by Epic. LootLedger reads replay files that Fortnite saves locally; it bundles no game assets.

**FortniteReplayDecompressor** (Shiqan and contributors, including OozSharp by SL-x-TnT and Shiqan): MIT. Source: https://github.com/Shiqan/FortniteReplayDecompressor, commit `76f74c1`. It is vendored in `replay-reader/vendor/FortniteReplayDecompressor` with a small patch described in `VENDORED.md` and `lootledger.patch`. Its licence is copied to `licenses/FortniteReplayDecompressor` in the build.

**.NET runtime** (Microsoft, MIT) is embedded in the self-contained `LootLedger.ReplayReader.exe`. Its `LICENSE.txt` and `ThirdPartyNotices.txt` are copied to `licenses/dotnet-runtime`. **Microsoft.Extensions.Logging.Abstractions**: MIT.

**Qt for Python / PySide6 Essentials and Shiboken** are provided under their applicable LGPL/GPL/commercial terms. The portable build dynamically bundles the native Qt libraries. Consult [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) and keep the bundled upstream notices when distributing builds. PyInstaller's licence includes its application distribution exception.

The retired screen detector, kept in source only, used OpenCV (Apache-2.0), NumPy (BSD-3-Clause), MSS (MIT), PyWinRT (MIT), ONNX Runtime (MIT), and a model fine-tuned from TorchVision SSDLite weights (BSD-3-Clause; see `lootledger/assets/MODEL-NOTICE.txt`). These are not part of the v0.4 desktop build.
