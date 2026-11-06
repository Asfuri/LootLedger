# Supplied gameplay analysis — 5 November 2026

**The existing detector missed all four openings in this clip. Repeating calibration does not solve the observed recognition failure.**

Recording: `Battle Royale Build Unranked Duo - 40 Left.mp4`, 1920×1080, 608 frames, approximately 29.996 FPS, duration 20.269 seconds. Completion timestamps below are approximate visual labels from before/after frames and interaction progress, independent of XP amounts.

| Successful personal opening | Approximate completion | Observed sequence |
| --- | --- | --- |
| First chest by the tree | 1.6 s | Closed chest, filling SEARCH circle, completion, opened chest, chest-specific XP |
| First chest beside the rock | 10.6 s | A different camera angle; filling SEARCH circle, completion and opened chest |
| Second chest beside the rock | 11.8 s | Separate search approximately 1.2 s later; reward label changes from CHEST to CHEST X2 |
| Chest on top of the rock | 17.4 s | Another viewpoint and search location; completion, opened chest and chest-specific XP |

Type remains **Unknown** for all four. Gold appearance alone does not establish an official type name.

## Existing detector results

The complete offline pipeline used the saved three-step setup and its normal resizing from this recording to the setup's 2560×1440 resolution. Of 178 sampled observations, **none passed the active-play HUD gate**. There were **0 confirmed events, 0 review events, 4 missed openings, 0 false counts and 0 duplicates**. Zero false/duplicate counts here follows from producing no events; it does not establish useful accuracy.

Independent ungated appearance checks at 17 representative timestamps produced HUD scores 0.625–0.732, closed-chest scores 0.348–0.431 and opened-chest scores 0.275–0.459. The configured match threshold is 0.82. Lowering it cannot establish reliable class separation: incorrect states score in the same range. A SIFT/homography probe did not produce usable chest localization either.

The interaction indicator moves with the viewed chest, but the current progress/search regions are fixed. This is an additional architectural limitation; this run never reached the interaction stage because the active-play gate failed first. Its independent failure rate is not measured here.

## Specific source fix

The original parser required the entire label to be exactly CHEST, rejecting the observed CHEST X2 aggregation. The corrected source accepts the exact base label plus an explicit multiplier, still requires a spatially associated purple XP line, and requires repeated readings before an increment supplies a new token. XP amount changes never create tokens. Each token still needs a separate completed personal interaction before it can corroborate a confirmed opening. Detector revisions now invalidate earlier validation approvals.

All **56 automated tests passed**. A separate native Windows OCR sweep of the recording followed four notification tokens at 2.305, 11.402, 12.139 and 18.203 seconds, including the CHEST-to-CHEST-X2 transition. These are evidence availability times, delayed by OCR readability, and **are not automatic opening detections**. They do not validate chest recognition, personal attribution, spectator filtering or real-time throughput.

The complete baseline sweep took 300.53 seconds with other diagnostics running. The notification-only sweep took 102.38 seconds. These offline timings are not a controlled live benchmark, but neither demonstrates real-time operation.

The installed executable was not replaced. The main recognition stages still fail this footage; automatic confirmations remain disabled. No report was attached to the live profile and no openings were added to the ledger.

## Replacement required

Replace the saved-picture matcher with a local object/state detector trained on labelled closed/opened chests across different views, and locate the associated interaction indicator as it moves. Replace the saved-HUD-picture gate with an active-play signal validated against personal play, lobby/results and spectating. Preserve temporal opening proof, exact chest-specific XP corroboration, per-event identities, Unknown types and uncertain-event review. Optimize and measure the pipeline's live frame rate before enabling it.

Use this labelled clip as a regression case. It is a small positive example with rapid openings and aggregated XP; it cannot supply the separate, varied training and held-out negative footage needed to validate the replacement. Do not train on these exact frames and then call the same frames an independent accuracy test.

## Records and reproduction

- [Approximate visual opening labels](reference-labels.json)
- [Complete original-detector baseline](reference-baseline.json)
- [Independent gate/appearance diagnostics](reference-stage-diagnostic.json)
- [Corrected notification component trace](reference-notifications.json)

The user's saved setup snapshot and raw frame observations are in `local-data/reference-video` on the development machine. To repeat the complete analysis from the workspace (the installed app's profile is not changed):

```powershell
.\.venv\Scripts\python.exe -m lootledger.analyze `
  '%USERPROFILE%\AppData\Local\Zeren\profiles\local\uploads\af0ce4ac-Battle_Royale_Build_Unranked_Duo_-_40_Left.mp4' `
  --config local-data\reference-video\original-profile.json `
  --labels validation\reference-labels.json `
  --output local-data\reference-video\rerun.json
```

This rerun uses the current source, including the notification fix; the unchanged HUD gate still blocks recognition. The stored baseline report records the source/profile fingerprint used before that fix. Both remain unapproved for automatic totals.
