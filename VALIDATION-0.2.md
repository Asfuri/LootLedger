# LootLedger 0.2 validation

Date: 5 November 2026. Windows 11 x64, Python 3.14.2, NVIDIA RTX 3060. Earlier prototype results are preserved in [VALIDATION-0.1.md](VALIDATION-0.1.md).

## Recorded gameplay: training-source regression

The supplied 1920x1080 recording lasts 20.269 seconds and contains four visually labelled personal openings. Version 0.2 produces four **review candidates**, at 1.601, 10.698, 11.802 and 17.373 seconds. At 0.5-second matching tolerance, candidate metrics are **4 matched, 0 missed, 0 false and 0 duplicates** in this recording. It produces **zero internally confirmed events**, so confirmed-opening metrics remain 0 matched and 4 missed. Review candidates are excluded from the ledger's confirmed totals.

This recording and the user's setup pictures were used for training. The result is an in-sample regression, **not an independent accuracy result or proof of live reliability**. The report records the training overlap and blocks approval. All types remain Unknown. No detections were imported into the user's ledger.

The model was fine-tuned with scene annotations, chest crops, player-only backgrounds, and random placement/size/flip examples. The corrected model localizes the world chests and recognizes the opened state in the inspected frames. The two inspected player-only frames at 3 and 6 seconds produce no model detections. The architecture is TorchVision SSDLite MobileNetV3 Large; seed 19, batch 4, 600 steps, 512-pixel input. Model provenance, hashes and limitations are included with its assets.

DirectML inference in the localization probe measured approximately 14-25 ms per frame. The complete 178-sample regression took 53.02 seconds while other checks were running; this includes decoding, startup, optical flow and OCR. It is not a controlled live frame-rate benchmark.

The lower-rate 5 Hz regression produced only two review candidates (1.567 and 11.835 seconds): 2 matched, 2 missed, 0 false and 0 duplicates. It missed part of the rapid pair and sampled the last search before the near-completion threshold. This is an observed sampling limitation, not a passing accuracy result. Keep the default 10 Hz target; actual live cadence still needs testing.

The final packaged executable reproduced all four review candidates at the same timestamps. This isolated offline run took 26.59 seconds: 3.85 seconds to initialize, 14.65 seconds in the sampled perception/detector calls, and the remainder in video decoding and reporting. Median sampled-frame processing was 70.32 ms; the 95th percentile was 172.91 ms. These measurements exclude actual Fortnite capture and do not establish a sustained live sampling rate.

Records:

- [Visual opening labels](validation/reference-labels.json)
- [Current complete regression](validation/v0.2-model-regression.json)
- [Packaged executable regression and timing](validation/v0.2-frozen-regression.json)
- [Lower-rate regression and observed misses](validation/v0.2-five-fps-regression.json)
- [Localization/negative-frame probe](validation/v0.2-model-localization.json)
- [Training annotations](validation/chest-training-annotations.json)
- [Original detector: 0 of 4 openings](validation/reference-baseline.json)

## Source and executable checks

**71 tests passed, 0 failed**, in 63.65 seconds. The build script completed successfully and produced `dist-v0.2/LootLedger/LootLedger.exe`. Both source and packaged smoke checks passed: rendered dashboard, counter actions, screen/language setup without chest boxes, native Windows OCR on generated text, bundled model loading/blank-frame rejection, and ordinary 1920x1080 desktop capture. The packaged checks ran from outside the source directory. The rendered packaged setup was also inspected.

Tests cover temporal proof, cancellation, stale/lingering XP, rapid separate interactions, uncertain camera association, near-completion review, exact CHEST X2 parsing, amount-animation independence, no-XP camera loss, SQLite saving/audit/recovery/backups, source setup, native Windows OCR and model loading/coordinate projection. Final records are in [build and smoke checks](validation/v0.2-build-checks.json); UI images remain in `local-data/v0.2-source-smoke` and `local-data/v0.2-frozen-smoke`. The smoke tests use temporary ledgers and do not alter the user's counts. The old executable folder was retained.

Executable SHA-256: `854731aff626e2266fe0ff3a58acdb8031a268a459563a8cb206176e9aab13f0`.
Bundled model SHA-256: `a65b432a618b289b88c071b78cf9375311242672f0c2e416cfa8511d7b6d05cd`.

The new setup uses screen/window and language selection; it requires no chest photographs or manually selected circle. The model runs through ONNX Runtime DirectML with CPU fallback. Motion tracking uses a smaller image and maps positions to the captured frame. OCR startup loads the inference runtime first to avoid native ML DLL initialization conflicts on the tested Windows machine.

## Limits and release behavior

Only the supplied ornate-gold-chest appearances and English keyboard interaction UI have been checked. Other containers, cancelled searches, spectators and lobby/results have synthetic logic tests, but lack representative held-out gameplay. Non-English game labels, other HUD layouts, all chest types, exclusive fullscreen, mixed-DPI live capture and actual live Fortnite cadence still require testing. Desktop screen capture and offline playback are different checks.

A near-complete search followed by a structured chest award can create an uncertain review item when the opened state or object association is unclear. It cannot silently become a confirmed count. A matching independent validation report is required for automatic confirmations; training-source recordings cannot approve their model. No general accuracy percentage has been established.

The source and portable build retain manual match boundaries, existing local SQLite data, correction/undo, export/restore, global correction hotkeys and an ordinary optional overlay. No memory access, injection, network interception, gameplay automation, sprite detection or sprite tracking was added.
