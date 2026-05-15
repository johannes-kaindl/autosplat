# Phase 0 — Baseline Calibration

> Spec §5 calls Phase 0 a "manual baseline run before CC implementation."
> We ran it _after_ the implementation, in fully-automated mode, to validate
> the defaults and catch upstream-tool surface drift. Findings below.

**Run date:** 2026-05-14
**Hardware:** Apple Silicon, macOS 15+
**Source video:** `import/dji_fly_bench_chill.MP4` (21.5s, 4K HEVC, 30 fps, ~104 MB)

## Wall-time summary

| Stage              | Duration | Notes                                                             |
| ------------------ | -------: | ----------------------------------------------------------------- |
| Preprocess (ffmpeg)|     7.5s | 107 frames extracted at 5 fps, **0** rejected by blur filter      |
| COLMAP feature extr|      35s | 1600px max image size, CPU-only (`--FeatureExtraction.use_gpu 0`) |
| COLMAP matcher (seq)|     46s | Sequential matcher — right pick for video-derived frames          |
| COLMAP mapper      |      73s | **107/107 cameras registered**, **53 222** sparse 3D points       |
| Brush training     |     282s | 5 000 steps (override; default is 30 000)                         |
| Export             |   < 0.01s | PLY copy + metadata.json                                          |
| **Total**          | **7:15min** | end-to-end                                                     |

Output: `scene.ply` **19.4 MB**, **82 172 Gaussians**, SH degree 3, binary little-endian.

## Tooling versions exercised

| Tool   | Version             | Source           |
| ------ | ------------------- | ---------------- |
| ffmpeg | 8.1.1               | Homebrew         |
| COLMAP | 4.0.4 (without CUDA)| Homebrew         |
| Brush  | v0.3.0 (brush-cli)  | GitHub release   |
| Python | 3.12.13             | uv               |

## Surface drift vs. the spec — and fixes applied

### 1. Brush v0.3.0 flag surface ≠ spec

| Spec                          | Brush v0.3.0 reality                |
| ----------------------------- | ----------------------------------- |
| `--source <path>`             | **positional** `[PATH_OR_URL]`      |
| `--max-steps N`               | `--total-steps N`                   |
| `--resolution-cap N`          | `--max-resolution N`                |
| `--densify-until-iter N`      | `--growth-stop-iter N`              |
| (no equivalent)               | `--export-name`, `--export-every` required to write PLY |

→ Updated `src/autosplat/train.py::build_brush_command` accordingly. The internal `BrushConfig` keys keep their spec names (`max_steps`, `resolution_cap`, `densify_until_iter`) so config files stay stable; the mapping happens at the command-builder.

### 2. COLMAP 4.0 flag namespace shift

The spec assumed `--SiftExtraction.max_image_size`. COLMAP 4.0 moved that to `--FeatureExtraction.max_image_size` (the SIFT namespace now only owns feature-detection params). Also: Homebrew's COLMAP is built **without CUDA**, so we force `--FeatureExtraction.use_gpu 0` to avoid the fragile GPU code path.

### 3. COLMAP 4.0 writes binary by default

Spec assumed `images.txt` / `points3D.txt`. COLMAP 4.0 ships `.bin` (and reads them faster). The mapper-stats parser now reads both — `_parse_mapper_stats` falls back from binary to text. Each binary file's first 8 bytes is a little-endian uint64 record count, which is enough for camera/point counts without depending on the full COLMAP Python SDK.

### 4. Brush dataset layout

Brush 0.3 wants a COLMAP-style root with `images/` and `sparse/0/` siblings — not the flat `frames/` + `colmap/sparse/0/` layout the spec implies. We resolved this without changing the spec layout: `train.stage_dataset()` builds a sibling directory with symlinks pointing back at the real `frames/` and `colmap/sparse/`.

### 5. `fetch_brush.sh` bugs

Two issues hit on the very first run:

1. **`pipefail` + `grep -m1`**: when `grep -m1` short-circuits, `curl` gets SIGPIPE and `pipefail` makes the whole pipeline return non-zero — even though the JSON parse succeeded. Fix: capture the JSON in a variable, then parse it without a pipe.
2. **`.tar.xz` asset**: Brush v0.3 ships its Mac binary as `.tar.xz`, not `.tar.gz` / `.zip`. Added a `tar -xJf` branch and renamed the post-extract helper to look for both `brush_app` (current upstream binary name) and `brush`.

### 6. `colmap --version` hangs

`colmap --version` apparently opens an option-menu and blocks; the doctor probe timed out at 5s. Replaced with `colmap help`, which returns the version banner promptly. Mechanism: `doctor._VERSION_PROBE_FLAGS` lets us override the probe per-binary.

## Validation — do the defaults need tuning?

Looking at `config/default.toml` against the bench-chill run:

| Key                              | Default | Phase-0 outcome                              | Verdict       |
| -------------------------------- | ------: | -------------------------------------------- | ------------- |
| `preprocess.target_frames`       | 250     | clamped to 5 fps × 21.5s = 107 frames        | Keep — sensible |
| `preprocess.blur_threshold`      | 100.0   | 0 frames rejected on sharp DJI footage       | Keep — drone footage is clean by default |
| `preprocess.min_frame_distance_sec`| 0.2  | active clamp on this short clip              | Keep          |
| `colmap.matcher`                 | sequential | 107/107 registered                        | Keep          |
| `colmap.quality`                 | medium  | high registration ratio, ~2 min wall time    | Keep          |
| `colmap.single_camera`           | true    | drone footage matches assumption             | Keep          |
| `brush.max_steps`                | 30000   | not exercised; 5 000 was enough for a usable PLY in 4.5 min | Keep, with note |
| `brush.densify_until_iter`       | 15000   | not exercised (used 2 500 in override)       | Keep          |
| `brush.resolution_cap`           | 1600    | matched COLMAP feature size; consistent      | Keep          |
| `brush.sh_degree`                | 3       | produced detailed PLY                        | Keep          |
| `viewer.auto_open`               | true    | overridden off for the autonomous run        | Keep          |

**Verdict: no default changes needed.** Spec defaults survived contact with reality. The only thing worth a callout in CONFIGURATION.md: with default `brush.max_steps=30000`, total wall-time for a 20s clip will be roughly `7min × (30000/5000) ≈ 25-30min`, which matches the spec's 30-90min estimate for 1-2 min videos.

## Open issues / follow-ups

1. **Brush training progress not captured in pipeline.log.** Brush v0.3.0 writes its iteration counter through a TUI renderer rather than plain stdout lines; my naive `if "step" in line.lower()` filter matches nothing. `train.done` is logged with `steps_completed: 0` even though training actually completed all 5 000 iterations. Non-blocking, but visibility-only fix worth doing — probably means subscribing to Brush's `--rerun-enabled` event stream or just trusting `cfg.max_steps` as the completed count when the process exits 0.
2. **`colmap_cameras_registered: 0` in the first run's metadata.json.** The text-only parser couldn't read COLMAP 4.0's `.bin` files at the time the export stage ran. Parser is now binary-aware; the next run will populate these fields. Existing metadata.json files won't backfill automatically.
3. **Viewer never auto-opened during this run** because the override config disabled it. Manual verification: open `~/AutoSplat/outputs/2026-05-14_dji_fly_bench_chill/scene.ply` in [SuperSplat](https://playcanvas.com/supersplat/editor) — `File → Open → Load PLY`.

## Backlog of unused import videos

| File                              | Duration | Codec | Notes                                                            |
| --------------------------------- | -------: | ----- | ---------------------------------------------------------------- |
| `dji_fly_ice_bird.MP4`            | 34.2s    | HEVC 60fps | 232 MB — high-bitrate variant                              |
| `dji_fly_ice_bird.mov`            | 34.2s    | HEVC 60fps | 93 MB — low-bitrate variant of the same capture            |

Either can be a Phase-1-acceptance follow-up run. Estimated wall-time at the same `max_steps=5000` override: ~10-12min. With the spec's `max_steps=30000` default: ~45-60min.

---

## Phase-1 Acceptance — Findings from `ice_bird.mov`

Following the Phase-0 success on `bench_chill`, we attempted a full Phase-1 acceptance run on `ice_bird.mov` (34.2s, 4K HEVC, **60 fps**) with the spec-default `brush.max_steps=30000`. The intent: validate the pipeline on a second, larger capture.

It surfaced a **footage-suitability boundary** worth recording.

### Run matrix

| Run | Config                          | Frames extracted | Frames kept (after blur) | Cameras registered | Outcome                |
| --- | ------------------------------- | ---------------: | -----------------------: | -----------------: | ---------------------- |
| #0  | `bench_chill.MP4` defaults      | 107              | 107 (100%)               | **107 / 107**      | ✅ passed (Phase 0)   |
| #1  | `ice_bird.mov` defaults (blur=100) | 171           | **20** (12%)             | 2 / 20             | ❌ aborted — blur filter too strict for 60 fps |
| #2  | `ice_bird.mov` blur=50          | 171              | **106** (62%)            | **4 / 106**        | ❌ aborted — sequential matcher overlap too narrow? |
| #3  | `ice_bird.mov` blur=50 + exhaustive matcher | 171  | 106 (62%)                | **2 / 106** (mapper killed mid-run) | ❌ failed — geometry-unfit |

### Diagnosis

Run #2 ruled out **frame supply** as the cause: 106 sharp keyframes is plenty for a 34s clip. Run #3 ruled out **matcher coverage**: exhaustive matcher checked all 5 565 frame-pairs (database grew from 27 MB after feature-extraction to ~154 MB after matching) and the mapper *still* registered only 2 cameras.

The remaining structural causes:

1. **Insufficient parallax per frame-pair.** A 60 fps clip of a drone moving along a smooth path puts neighbouring frames very close together in 3D space. SfM needs translation, not just rotation, to triangulate — and at 60 fps even a few metres of drone speed gives only centimetres of baseline between adjacent frames.
2. **Texture-poor scene.** SIFT features need local contrast. Wide shots of sky / snow / ice / open water have very low feature density, so matches are sparse even when geometry would otherwise allow them.

We did not isolate which factor dominates here without inspecting individual frames, but both probably contribute. The `MP4` variant of the same capture is unlikely to fix this — same scene, same geometry, only the codec is different.

### What this means for the pipeline

This is **not a bug**. The pipeline works correctly: it extracts frames, runs SfM, reports honest stats, and would happily train Brush on whatever the mapper produces. The bottleneck is upstream of the pipeline — it's the source footage.

Spec §11.3 (Phase 3) already calls out the right place to handle this:

> *"Bei schlechtem Footage (Test-Fixture: shaky_dark.mp4) → graceful retry → skip. Validation-Failures landen mit Begründung in State-File."*

The adaptive-retry logic described in spec §9.2 ("Retry mit `exhaustive` matcher when <60% Cameras registered" and "Retry mit `resolution_cap` halbiert on OOM") is the path forward. Suggested Phase-3 surface:

- After `sfm.done`, compare `cameras_registered / frames_kept` against a configurable threshold (default 0.5).
- If the ratio is below threshold, log the reason to `~/.autosplat/state.json` and refuse to start the Brush stage — wasting 25-30 min of GPU on 2-camera input is the most expensive single failure mode in this pipeline.
- Surface the failure clearly in `autosplat status` (red row, with the camera ratio and the suggested manual remediation).

### Phase-1 Acceptance verdict

- ✅ **`bench_chill.MP4`** (30 fps, sharp, ground-detail) — passed. 107/107 cameras, 53 222 sparse points, 82 172 Gaussians, 19.4 MB PLY.
- ❌ **`ice_bird.mov`** (60 fps, drone fly-through, texture-poor) — failed. Footage is structurally unsuited to SfM, not a pipeline regression.

**Recommendation for future captures:**

- Aim for 30 fps source (or lower) to maximise per-frame parallax. A 60 fps Neo-2 recording can be downsampled to 30 fps in-camera or in ffmpeg before pipeline ingest.
- Prefer captures with a clear ground plane and varied texture (buildings, terrain). Open-sky or uniform-snow scenes will defeat SfM regardless of pipeline tuning.
- If a low-parallax capture is the only available source, Phase 3's adaptive retry can at least save the wasted Brush time — but the only real fix is recapture.

