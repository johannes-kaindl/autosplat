# Troubleshooting

Known failure modes, mapped to the stages they happen at. The Phase-3 quality-gate and Phase-6 adaptive-retry handle most of these automatically — this doc is mostly for the cases the watcher can't fix on its own, plus the failure modes the daemon does fix so you understand what you're seeing.

## `autosplat doctor` reports MISSING / WARN

| Tool       | Status row | Fix                                                                                    |
| ---------- | ---------- | -------------------------------------------------------------------------------------- |
| `ffmpeg`   | MISSING    | `brew install ffmpeg`                                                                  |
| `colmap`   | MISSING    | `brew install colmap`                                                                  |
| `brush`    | MISSING    | `./scripts/fetch_brush.sh` (manual fallback in the script's stderr)                    |
| `platform` | (warn)     | auto-splat-pipeline is Mac-Silicon-only. x86 Macs and Linux unsupported.               |
| `compress` | WARN       | Optional (Phase 5). Install Node.js (`brew install node`) — pipeline auto-uses `npx`.   |
| `obsidian` | WARN       | Phase 8. `[obsidian].enabled = true` but `vault_path` is empty or missing on disk.     |

## "Brush binary missing"

```bash
./scripts/fetch_brush.sh
```

If GitHub asset auto-detection fails (Brush's release naming may change), the script prints manual instructions. Drop the binary at `~/AutoSplat/bin/brush`, `chmod +x` it, write the version into `~/AutoSplat/bin/.brush-version`, and re-run `autosplat doctor`.

## Pre-flight rejected my video (Phase 6)

You'll see one of these in the log:

```
{"event":"preflight.failed","reason":"video_corrupt", …}
{"event":"preflight.failed","reason":"implausible_duration", …}
{"event":"preflight.failed","reason":"implausible_resolution", …}
{"event":"preflight.failed","reason":"implausible_fps", …}
```

- **`video_corrupt`**: ffprobe couldn't parse the file. Re-export the video from your phone/drone editor, or run `ffprobe -v error -i <video>` manually to see the underlying error.
- **`implausible_duration`**: shorter than 3 s or longer than 10 min. Trim or split it in ffmpeg / iMovie. The spec considers anything outside that range to be a misclick.
- **`implausible_resolution`**: shortest side below 720 px. Upscale isn't useful — recapture at ≥720p.
- **`implausible_fps`**: below 23 fps or above 120 fps. Below 23 = something's odd; above 120 = high-speed phone capture, which usually won't have enough parallax for SfM anyway.

Thresholds live in `src/autosplat/preflight.py` as module constants. If your use-case needs different bounds, edit there.

## All frames rejected as blurry / pipeline aborts immediately (Phase 6)

Typical with DJI Osmo Pocket / Action HDR footage. You'll see one of:

```
{"event":"preprocess.all_frames_rejected", …}
{"event":"preprocess.too_few_frames", …}
```

Two mechanisms now handle the common causes automatically:

- **HDR is auto-tone-mapped.** HLG (`color_transfer=arib-std-b67`) or PQ (`smpte2084`) footage — including DJI Mimo's one-tap "HDR" / Dolby-Vision exports — decodes flat and grey, scoring ~3–20 on the Laplacian blur metric (vs 100–500 for normal SDR), so the whole clip used to be rejected. `probe_video` now detects HDR via ffprobe and `extract_hdr_frames` tone-maps each frame to SDR Rec.709 during extraction (`preprocess.hdr_tonemap`, default `true`). Stock ffmpeg only — no `zscale`/`libplacebo` needed.
- **Adaptive blur rescue.** When `blur_threshold` would leave fewer than 3 usable frames, the pipeline keeps the frames that are sharp *relative to the batch* (≥ `blur_rescue_rel_factor` of the median) instead of failing — the absolute threshold is calibrated for sharp SDR and is meaningless for soft footage. Toggle via `preprocess.blur_rescue` (default `true`) and `preprocess.blur_rescue_rel_factor` (default `0.6`).

If it still fails with both enabled, the footage is genuinely too soft (out of focus, motion-blurred, or a heavily re-compressed export). Prefer the microSD originals over Mimo `*_compose_0` files, and see [`CAPTURE-GUIDE.md`](CAPTURE-GUIDE.md) — recording in SDR ("Normal") at source is sharper than any tone-mapped HDR re-encode.

Re-running `autosplat process` on the same capture-dir after fixing footage/config is safe — `run_colmap` wipes the stale COLMAP database + `sparse/` before a fresh run, so old and new features no longer mix. (`autosplat resume` is unaffected — it never re-runs COLMAP.)

## Brush ran out of memory (Phase 6 — auto-retry)

You'll see in the log:

```
{"event":"train.brush.oom_detected","resolution_cap":1600, …}
{"event":"watcher.brush_oom","resolution_cap_attempted":1600,"next_resolution_cap":800,"outcome":"retry", …}
```

The watcher detected the OOM, scheduled a retry with halved `resolution_cap`. **Nothing for you to do** unless retries hit the cap. If retries are exhausted you'll see the entry in `autosplat status`'s `Recent failures` table with reason `brush_oom: resolution_cap=…`.

To avoid OOM upfront: lower `[brush].resolution_cap` in your config (1600 → 1200 → 800).

## ffmpeg "skipped N frames" warning (Phase 6)

You'll see:

```
{"event":"preprocess.skipped_frames","skipped":12,"threshold":12,"hint":"ffmpeg dropped duplicate frames…"}
```

This is **usually harmless** — ffmpeg drops near-duplicate frames during extraction. Threshold is 5 % of `target_frames`. If the count is much higher than 5 %, your source may have static stretches (drone hovering); consider lowering `target_frames`.

## Quality-gate refuses to start Brush

You'll see a structured log:

```
{"event":"quality_gate.failed","reason":"low_camera_ratio: 0.04 < 0.5",
 "retry_hint":{"colmap":{"matcher":"exhaustive"}},
 "metrics":{"cameras_registered":4,"frames_kept":106,"matcher":"sequential"}}
```

This is *desired* behaviour — the gate spared you ~30 min of Brush compute on garbage SfM. What to do next:

- **`autosplat watch` mode:** nothing — the daemon already re-enqueued with `matcher=exhaustive`. Wait for the retry.
- **`autosplat process` mode:** the in-process adaptive-retry wrapper does the same matcher swap automatically — you usually don't need to do anything. The run only exits with code 2 if the swap also fails.
- **If `exhaustive` also fails (`retry_hint=null` in the log):** v1.4 escalates automatically to *auto-bisection-rescue* — the source video is binary-subdivided and each leaf clip probed independently. Watch `pipeline.log` for `bisection.*` events:
  ```
  pipeline.bisection_escalation reason="low_camera_ratio: 0.02 < 0.5"
  bisection.start            video=… duration_s=335.0
  bisection.probe            clip_id=0 cameras_registered=4 ratio=0.03 passed=false
  bisection.probe            clip_id=0_1 cameras_registered=78 ratio=0.62 passed=true
  bisection.combine_start    leaf_count=2
  ```
  Surviving leaves persist as `<capture_dir>/rescue/clips/*.mp4` and are then fed through the multi-video pipeline path. See [`CAPTURE-GUIDE.md`](CAPTURE-GUIDE.md#auto-bisection-internals-v14) for the on-disk layout and config knobs.
- **If even bisection produces no leaves (`bisection_exhausted`):** the footage is structurally SfM-unfit (low parallax / texture-poor). See `PHASE-0-CALIBRATION.md` for the `ice_bird` case study — only fix is recapture at ≤30 fps with more ground detail / texture. Set `[retry] bisect_enabled = false` in CI to short-circuit this branch.

To bypass the gate entirely (not recommended, you'll waste Brush time):

```toml
[quality_gate]
enabled = false
```

## Adaptive retry isn't kicking in

Check:

```bash
autosplat config show | grep -A2 retry
```

If `enabled = false` or `max_retries = 1`, retries are off. Set them in your user config:

```toml
[retry]
enabled = true
max_retries = 3
```

State of the per-path retries lives in `~/.autosplat/state.json` under `retry_state` — `autosplat status` doesn't render it yet (todo).

## Pipeline failure → "PLY validation failed"

The exported `.ply` is too small (<100 KB) or has an invalid header. Almost always means Brush exited early. Check `<capture-dir>/pipeline.log` — Brush's tail lines are routed through structlog at DEBUG. Re-run with `[logging].level = "DEBUG"` to see them on console.

## COLMAP registers very few cameras

Phase 3 now catches this. If you've disabled `[quality_gate]`:

- For sequential matcher: retry with `matcher = "exhaustive"`
- If still bad: the footage isn't SfM-suitable. See `PHASE-0-CALIBRATION.md`.

## Out-of-memory during Brush training

**Phase 6 now auto-retries OOM with halved `resolution_cap`.** See the section "Brush ran out of memory" above. The manual fixes below are only relevant if you want to prevent OOM in the first place (saving the retry-attempt cost):

```toml
[brush]
max_steps = 15000          # half of default
resolution_cap = 800       # half of default
sh_degree = 2              # less view-dependent colour
```

If even `resolution_cap=256` (the Pydantic minimum, what auto-retry will eventually hit) OOMs: the source video is too big for your machine. Recapture at lower resolution.

## "Watch folder does not exist"

`mkdir -p ~/AutoSplat/inbox` (or point `[paths].watch_folder` somewhere that does exist).

## Daemon recovers, but the capture is gone from the queue

Phase 3 adaptive retry: if `retry.enabled` and the orphan capture's `retry_state[path].attempts < max_retries`, the daemon re-enqueues silently. Look for `watcher.recovered action=re_enqueued` in the log. If you want crashed captures to *always* go to `failed` regardless, set `[retry].enabled = false`.

## Same video processed twice

The watcher de-dupes by path while a capture is in flight and against the queue. Drop the same file twice and you get one run. Drop it again *after* the first capture has been moved to `completed`, and the second drop will run again — different `{date}_{stem}` capture-dir if the date differs. Future Phase-6: content-hash dedup against `completed`.

## Viewer doesn't open / opens but doesn't load the splat

The SuperSplat URL embeds a local `http://127.0.0.1:<port>/scene.ply` link. Browser fetches from the local server. If load fails:

- Big PLY (>50 MB): give it 10-15 s
- Console errors (CORS): try `--target playcanvas` in TOML instead
- Manual workaround: open SuperSplat, drag the `.ply` from Finder onto the canvas

See `docs/PLY-OUTPUT-FORMAT.md` for the viewer compatibility matrix.

## Obsidian note overwrites my prose

The auto-generator preserves everything **after** the `<!-- AUTO-GENERATED:END -->` marker on re-runs. If you wrote prose *inside* the marker block, it's lost on the next re-render.

- The right place for your prose: under `## Notes` (which lives below the END marker by default).
- If the file existed *before* you enabled Obsidian and had no markers, it's backed up to `<file>.bak` on first auto-write — your original content is recoverable.

**Phase 8 — Frontmatter user-keys also survive.** If you add a frontmatter field like `location:` or `flight_notes:` (anything not in the Cowork-managed list), it's preserved on every re-run. Same for `embed_url:` after you've published to SuperSplat — once set to a non-null value, it stays.

## Obsidian doctor says vault_path empty

Phase 8 changed the default — `[obsidian].vault_path` is now empty by default rather than `~/Documents/Vault`. If you enable Obsidian, you must set the path explicitly:

```toml
[obsidian]
enabled = true
vault_path = "/Users/you/Documents/MyVault"   # ← required
captures_subdir = "Captures"                   # adjust to fit your vault
```

`autosplat doctor` will switch from WARN → OK once both fields resolve to an existing directory.

## Re-running a half-failed capture by hand

Each stage is idempotent. To resume past a failed stage manually:

```bash
autosplat process video.mp4 --skip-stage preprocess --skip-stage sfm
```

(Only training + export run.) Note: `export` cannot be skipped.

## Log file is missing or empty

`[logging].log_to_file = false` disables `pipeline.log`. Console output goes to stderr — pipe accordingly if you want to capture it. The watcher itself logs to stderr only; per-capture logs are still in each capture-dir.
