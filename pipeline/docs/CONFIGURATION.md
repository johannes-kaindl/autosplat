# Configuration

`autosplat` reads config in layers, with later layers winning:

1. **Packaged defaults** — `config/default.toml` (always loaded)
2. **User XDG config** — `~/.config/autosplat/config.toml` (loaded if it exists)
3. **Explicit override** — `autosplat <command> --config <path>`
4. **Per-attempt override** — Phase-3 adaptive-retry can deep-merge a hint dict (e.g. `{"colmap": {"matcher": "exhaustive"}}`) on top of the resolved config for a single retry. Not user-facing.

To produce a starting point:

```bash
autosplat config init                # writes ~/.config/autosplat/config.toml
autosplat config init -t ./my.toml   # writes to a custom location
```

To inspect what's actually being used after merging:

```bash
autosplat config show
```

---

## `[paths]`

| Key            | Default                       | Notes                                                                                     |
| -------------- | ----------------------------- | ----------------------------------------------------------------------------------------- |
| `captures_dir` | `~/AutoSplat/captures`        | Per-capture working dirs.                                                                 |
| `watch_folder` | `~/AutoSplat/inbox`           | Drop videos here for `autosplat watch`.                                                   |
| `brush_binary` | `~/AutoSplat/bin/brush`       | Resolved by `scripts/fetch_brush.sh`. Override if you keep binaries elsewhere.            |

`~` is expanded at load time.

## `[preprocess]`

| Key                     | Default | Notes                                                                                                   |
| ----------------------- | ------- | ------------------------------------------------------------------------------------------------------- |
| `target_frames`         | `250`   | Target keyframe count. Actual count may be slightly higher; blur filter drops some.                     |
| `blur_threshold`        | `100.0` | Laplacian-variance floor. Frames below this are discarded. **High-fps drone footage may need 25–50** — see `PHASE-0-CALIBRATION.md` (ice_bird @ 60 fps loses 88 % of frames at default 100). |
| `min_frame_distance_sec`| `0.2`   | Minimum temporal spacing between extracted frames — prevents near-duplicates in slow-motion sections.   |

## `[colmap]`

| Key             | Default        | Values                                                | Notes                                            |
| --------------- | -------------- | ----------------------------------------------------- | ------------------------------------------------ |
| `matcher`       | `"sequential"` | `sequential` · `exhaustive` · `spatial` · `vocab_tree` | `sequential` is fastest for video; the gate auto-suggests `exhaustive` on retry. |
| `quality`       | `"medium"`     | `low` · `medium` · `high`                              | Controls `max_image_size` + `max_num_features`.  |
| `single_camera` | `true`         | bool                                                   | True for drone footage (one physical camera).    |

Quality presets:

| Preset | `max_image_size` | `max_num_features` |
| ------ | ---------------- | ------------------ |
| low    | 1200             | 4096               |
| medium | 1600             | 8192               |
| high   | 2400             | 16384              |

## `[brush]`

| Key                  | Default | Notes                                                                            |
| -------------------- | ------- | -------------------------------------------------------------------------------- |
| `max_steps`          | `30000` | Total training iterations. Mapped to `--total-steps` on Brush v0.3.              |
| `resolution_cap`     | `1600`  | Mapped to `--max-resolution`. Brush downsamples training images to this.         |
| `sh_degree`          | `3`     | Spherical-harmonic degree. 0=ambient only, 3=detailed view-dependent colour.     |
| `densify_until_iter` | `15000` | Mapped to `--growth-stop-iter`. Stop adding new gaussians after this iteration.  |
| `extra_args`         | `[]`    | Passthrough for advanced Brush flags. Appended after the canonical ones.         |

## `[export]`

| Key               | Default                     | Notes                                                              |
| ----------------- | --------------------------- | ------------------------------------------------------------------ |
| `formats`         | `["ply"]`                   | Phase-1: ply only. Use the `compress` subcommand for SOG/SPZ.      |
| `copy_to_outputs` | `true`                      | Also copies final ply to `outputs_dir/<capture_name>/`.            |
| `outputs_dir`     | `~/AutoSplat/outputs`       | Where the user-facing final PLYs land.                             |

## `[viewer]`

| Key               | Default        | Values                                | Notes                                                         |
| ----------------- | -------------- | ------------------------------------- | ------------------------------------------------------------- |
| `auto_open`       | `true`         | bool                                  | If false, the run finishes without opening a browser.         |
| `local_http_port` | `8765`         | int                                   | Local server port for serving the .ply to the viewer.         |
| `target`          | `"supersplat"` | `supersplat` · `playcanvas` · `none`  | Which viewer URL to open. `none` disables viewer entirely.    |

## `[obsidian]` (Phase 4 + 8 — opt-in)

| Key                | Default                              | Notes                                                                    |
| ------------------ | ------------------------------------ | ------------------------------------------------------------------------ |
| `enabled`          | `false`                              | Master switch. Off by default.                                           |
| `vault_path`       | `""` (empty)                         | **Phase 8:** must be set by you. Empty = no path; doctor warns + writes are skipped. |
| `captures_subdir`  | `"Captures"`                         | **Phase 8:** vault-neutral default. Override to match your vault convention (e.g. `40_Zettelkasten/3D-Captures`). |
| `attach_ply`       | `false`                              | If true, copy the PLY into the vault. Big files — opt-in.                |
| `filename_pattern` | `"{capture_date} {video_stem}.md"`   | Placeholders: `{capture_date}` `{video_stem}` `{capture_name}`.          |
| `default_tags`     | `["3d-memory", "gaussian-splat", "auto-splat"]` | Frontmatter `tags:` list.                                  |
| `frontmatter_type` | `"capture"`                          | Frontmatter `type:` field — used by Obsidian Bases for dataview-style queries. Adjust to fit your vault's `_types/` vocabulary. |

The capture-note body contains an auto-block bracketed by:

```
<!-- AUTO-GENERATED:START — managed by autosplat, do not edit between markers -->
…stats / source / output…
<!-- AUTO-GENERATED:END -->
```

Anything you write **after** the END marker is preserved across re-runs. If the file exists without markers (you wrote a hand-typed note there before enabling Obsidian), it's backed up to `<file>.bak` and the fresh template is written.

**Phase 8 — Frontmatter user-key-preservation:**

- *Cowork-managed keys* (`type`, `captured`, `source`, `frames_*`, `cameras_registered`, `points3d`, `gaussians`, `sh_degree`, `training_duration_s`, `total_duration_s`, `output_ply`, `output_ply_size_bytes`, `tags`): always re-generated on each run — if you edit these, your edit is overwritten next run.
- *`embed_url`*: if you've manually filled it in (e.g. after publishing to SuperSplat) and a new pipeline run has `embed_url: null`, your value is preserved.
- *Any other key you add* (e.g. `location`, `weather`, `flight_notes`): preserved untouched across re-runs.

Want to attach a `location` or `weather` field to your captures? Just add it to the frontmatter — autosplat will leave it alone.

## `[preflight]` (Phase 6 — non-configurable, mentioned for completeness)

There's no `[preflight]` section in TOML — the plausibility thresholds are constants in `src/autosplat/preflight.py`:

| Constant          | Value      | Means                                                |
| ----------------- | ---------: | ---------------------------------------------------- |
| `MIN_DURATION_S`  | `3.0`      | Reject videos shorter than 3 seconds                 |
| `MAX_DURATION_S`  | `600.0`    | Reject videos longer than 10 minutes                 |
| `MIN_RESOLUTION`  | `720`      | Reject videos where `min(width, height) < 720`       |
| `MIN_FPS`         | `23.0`     | Reject videos below cinema 24 / NTSC 23.976          |
| `MAX_FPS`         | `120.0`    | Reject videos above 120 fps (high-speed phones cap)  |

These are intentionally permissive; if you have a use-case for tighter bounds (or a "10 hour timelapse" exception), open an issue. Pipeline-disable: not possible — preflight always runs after the dry-run gate.

`ffprobe` failure (corrupt file, no video stream) → `PreflightFailure(reason="video_corrupt", …)` no matter what.

## `[quality_gate]` (Phase 3)

| Key                | Default | Notes                                                                                |
| ------------------ | ------- | ------------------------------------------------------------------------------------ |
| `enabled`          | `true`  | Bail out of the pipeline before Brush if SfM is bad.                                 |
| `min_camera_ratio` | `0.5`   | Required `cameras_registered / frames_kept` ratio.                                   |
| `min_points`       | `5000`  | Required absolute COLMAP sparse-point count.                                         |

Defaults derived from Phase-0 calibration (`bench_chill`: ratio 1.0 / 53 222 points; `ice_bird`: 0.04 / 642 points).

On fail, raises `QualityGateFailure(reason, stage, retry_hint, metrics)`. The watcher consults the hint and decides retry vs final-fail.

## `[retry]` (Phase 3 watcher policy)

| Key            | Default | Notes                                                                  |
| -------------- | ------- | ---------------------------------------------------------------------- |
| `enabled`      | `true`  | Master switch for adaptive retry.                                      |
| `max_retries`  | `3`     | Maximum total attempts per capture, including the first try.           |

Applies to:
- Crashes (`recover_state` finds an orphan `in_progress`)
- Quality-gate failures with a non-None `retry_hint`
- Generic exceptions during processing

## `[status]` (Phase 3 history bound)

| Key            | Default | Notes                                                          |
| -------------- | ------- | -------------------------------------------------------------- |
| `max_history`  | `50`    | FIFO trim for `completed` and `failed` lists in `state.json`.  |

## `[logging]`

| Key           | Default  | Values                                              | Notes                                                        |
| ------------- | -------- | --------------------------------------------------- | ------------------------------------------------------------ |
| `level`       | `"INFO"` | `DEBUG` · `INFO` · `WARNING` · `ERROR` · `CRITICAL` | Controls both console and file output.                       |
| `console`     | `"rich"` | `rich` · `plain`                                    | `plain` for unattended runs / CI logs.                       |
| `log_to_file` | `true`   | bool                                                | If true, writes `pipeline.log` (JSON) into the capture dir.  |
