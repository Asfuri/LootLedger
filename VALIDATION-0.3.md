# LootLedger 0.3 validation

Date: 6 November 2026. Windows 11 x64, Python 3.14.2, RTX 3060. Prior release records are retained in [VALIDATION-0.2.md](VALIDATION-0.2.md).

## Reproduced failure

The new supplied recording is 1920x1080, 304 frames, about 10.14 seconds. Visual opening labels are 2.05 and 8.25 seconds, bracketed to approximately 0.05 seconds by adjacent closed/opened frames. The unchanged v0.2 EXE, tested before detector changes, produced only one review candidate at 2.063 seconds: 1 matched, 1 missed, no false/duplicate candidates, and zero confirmed events. [Baseline](validation/new-clip-v0.2-baseline.json), [visual labels](validation/new-clip-labels.json).

The selected display was verified to contain the Fortnite window at 2560x1440. The failures were in perception and timing: the chest model disappeared during the downward camera turn; the temporal detector discarded early progress and treated brief OCR misses as cancellation; opened-state predictions flickered; OCR zoom/resizing damaged small award text. OCR profiling also recorded calls longer than half a second. The positive offline pass from v0.2 had not established live reliability. [Profile](validation/new-clip-stage-profile.json).

## What changed

The model weights are unchanged (SHA-256 `a65b432a618b289b88c071b78cf9375311242672f0c2e416cfa8511d7b6d05cd`). No training images from the new clip were added. The detector now preserves first-frame progress, allows a short OCR gap without silently confirming it, and retains uncertain identity through brief model gaps. Forward/backward optical flow and photometric error reject failed motion tracking. A fresh model detection can rejoin a recent chest as uncertain when the lid changes appearance; optical flow alone never supplies an opened state. Opened-state flicker can create review evidence while consecutive readings remain necessary for strong confirmation.

The model facade limits processing to 1080p with cubic resampling. OCR reads text-sized bands in the selected regions instead of repeatedly scanning large world-background crops, uses stable label width for the English interaction circle, and adapts award zoom after an exact structured reading. Only trailing dots/commas are normalized; misspelled/partial CHEST labels and extra words remain rejected. No XP amount is assumed or divided. Status includes the measured scan rate. No three-box setup is required.

## Checks and release limits

The complete source suite passed **82 tests** in 18.75 seconds. Tests include early progress, cancellation versus OCR dropout, camera cuts, uncertain motion/reacquisition, state flicker, label parsing, real Windows OCR on generated text, high-resolution normalization, persistence/backup/recovery and the existing UI/counter behavior. Build and packaged checks are recorded in `validation/v0.3-build-checks.json` after completion.

Source development regression: two review candidates matched the new clip, and four matched the original clip, without observed false/duplicate candidates in those clips. The original recording was used for model training. The second recording was not used for model training, but was used to debug the detector; neither result establishes independent accuracy. Confirmed-event metrics remain separate from review-candidate metrics.

Timed fixtures run the actual worker at wall-clock speed against lossless frames in a temporary ledger, including a 2560x1440 simulation. Intermediate timed trials missed an opening and exposed the timing/resize bugs. The final packaged report, effective sample rate and latency are documented after the EXE checks. This fixture does not establish actual foreground capture, spectator filtering, other chest appearances or live gameplay accuracy.

The executable gate remains closed: candidates require Confirm, are excluded from confirmed totals, and all chest types remain Unknown. Representative held-out footage containing other containers, cancelled searches, overlapping awards, rapid openings and spectating is still needed. Synthetic negative tests do not establish gameplay false-positive rates. No new clip detections were imported into the user's ledger. Source and smoke/replay checks use temporary data.

Records: [new clip](validation/v0.3-new-clip-regression.json), [original clip](validation/v0.3-original-regression.json), [source timed replay](validation/v0.3-realtime-1440.json), [early timed failure](validation/v0.3-early-realtime-1440.json).

## Final packaged checks

The build completed and the standalone EXE passed its Windows UI/counter, screen/language setup, native OCR, model-load/blank-frame and ordinary 1920x1080 desktop-capture smoke checks. It ran from outside the source directory; the rendered setup was inspected.

| Packaged check | Matched review candidates | Missed | False | Duplicate |
|---|---:|---:|---:|---:|
| New clip, offline | 2 / 2 | 0 | 0 | 0 |
| Original training-source clip, offline | 4 / 4 | 0 | 0 | 0 |
| New clip, timed 2560x1440 fixture | 2 / 2 | 0 | 0 | 0 |

The timed packaged run processed 90 frames in the 10.15-second fixture, averaging 8.87 scans/s. Median perception processing was 72.07 ms; its 95th percentile was 147.44 ms. Candidate timestamps were 2.065s, 8.306s. Timing is specific to this fixture/machine; it excludes actual screen capture, foreground checks and UI drawing.

All of these events are **review candidates**, with zero confirmed counts. Thus confirmed-event metrics still miss the labelled openings; candidate metrics above describe review recall only. No general accuracy percentage or negative-gameplay false-positive rate has been measured.

[New packaged analysis](validation/v0.3-frozen-new-clip.json), [original packaged analysis](validation/v0.3-frozen-original.json), [packaged timed worker](validation/v0.3-frozen-realtime-1440.json), [complete build checks](validation/v0.3-build-checks.json).

Executable SHA-256: `e28f60fee2ebc0c4007097745545f39062efc2ba8a0bb99f1c60789f03d3ddcb`. Keep the complete `dist-v0.3/LootLedger` directory. Existing counts/settings use the same local data directory.
