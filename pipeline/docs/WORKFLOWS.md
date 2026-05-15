# Workflows

User-facing recipes. Pick the one that matches what you're trying to do.

---

## 1. One-shot run on a single video

Use when you have a specific clip you want to process right now.

```bash
autosplat process import/bench_chill.MP4
```

What happens:

1. Pre-flight: ffprobe validates the video + checks duration/resolution/fps plausibility (Phase 6)
2. ffmpeg extracts ~250 keyframes at 5 fps (capped by `min_frame_distance_sec`)
3. COLMAP feature-extract → matcher → mapper produces `sparse/0/`
4. Quality-gate validates `cameras_registered / frames_kept ≥ 0.5` and `points ≥ 5000` (Phase 3)
5. Brush trains 30 000 steps on the COLMAP dataset — **a Rich progress bar shows elapsed time + ETA** (Phase 7, TTY only)
6. `scene.ply` is validated (≥1 MB), copied to `~/AutoSplat/outputs/<capture>/`
7. Optional: `autosplat compress` post-step if `[compress].enabled = true` (Phase 5)
8. SuperSplat opens in your browser with the splat auto-loaded

Wall-time on a 21 s 4K clip (M5, 30 000 steps): ~35–45 min. The progress bar makes the long-running Brush stage feel much less opaque.

Useful flags:

```bash
autosplat process video.mp4 \
  --config ~/my-overrides.toml          # use a custom TOML overlay
  --output-dir ./local-captures         # override captures_dir
  --skip-stage preprocess --skip-stage sfm   # resume past completed stages
  --dry-run                                  # print plan, do nothing
```

---

## 2. Watch-folder daemon — drop & forget

Use when you have multiple captures to process or want a long-running service.

```bash
# Make the inbox if it's not there
mkdir -p ~/AutoSplat/inbox

# Start the daemon (Ctrl-C to stop)
autosplat watch ~/AutoSplat/inbox
```

Then just drop `.mp4` / `.mov` / `.m4v` files into `~/AutoSplat/inbox`. They get:

- Detected by watchdog after a size-stability poll (so half-uploaded files don't fire)
- Enqueued in `~/.autosplat/state.json`
- Processed FIFO, one at a time

Crash safety: kill the daemon mid-Brush and the state file stays consistent. Restart with `autosplat watch` and the orphan is re-enqueued (or moved to `failed` if it's hit `max_retries`).

One-pass variant:

```bash
autosplat watch --once ~/AutoSplat/inbox    # drain existing files, then exit
```

---

## 3. Check what the daemon is doing

```bash
autosplat status
```

Shows three tables:

- **In progress** — path, stage, started timestamp
- **Recent completed** (last 10) — path, output PLY, duration, finished_at
- **Recent failures** (last 10) — path, stage, reason, failed_at

If the state file is empty (no daemon has ever run), you get a message saying so.

---

## 4. Inspect a finished PLY

A finished pipeline run drops the splat at `~/AutoSplat/outputs/<capture-name>/scene.ply`. Three ways to open it:

### a) SuperSplat (recommended)

Browser-based, no install. Best for cleanup + publish.

1. Open <https://playcanvas.com/supersplat/editor>
2. Drag the `.ply` from Finder onto the canvas, **or** File → Open → Load PLY
3. Orbit with mouse, paint-select floaters with the Brush tool, crop with the bounding-box tool

### b) Brush built-in viewer

Same engine as the trainer — useful for sanity-checking before SuperSplat.

```bash
~/AutoSplat/bin/brush ~/AutoSplat/outputs/<capture>/scene.ply --with-viewer
```

### c) Auto-open via the pipeline

If you set `[viewer].auto_open = true` (default), every successful `autosplat process` will pop SuperSplat at the end with the new splat URL.

---

## 5. Enable Obsidian capture notes

Use when you want every successful run to drop a structured note in your vault.

`~/.config/autosplat/config.toml`:

```toml
[obsidian]
enabled = true
vault_path = "/Users/you/Documents/MyVault"    # required — Phase 8 has no default
captures_subdir = "Captures"                    # adjust to your vault convention
filename_pattern = "{capture_date} {video_stem}.md"
frontmatter_type = "capture"                    # align with your _types/
default_tags = ["3d-memory", "gaussian-splat", "auto-splat"]
```

`autosplat doctor` will WARN if `enabled = true` but `vault_path` is empty or missing on disk — set it before your first run.

The resulting note has frontmatter with every numeric stat (`gaussians`, `sh_degree`, `cameras_registered`, …) plus an auto-block region in the body. **You can write anywhere after `<!-- AUTO-GENERATED:END -->`** and your prose survives re-runs.

The auto-block includes an `<iframe>` for the splat *if* you've filled in `embed_url:` in the frontmatter (e.g. with a SuperSplat publish URL).

**Phase 8 — user-key preservation:** any frontmatter key you add yourself (`location`, `weather`, `flight_notes`, …) is preserved across re-runs. `embed_url:` is special-cased: once you fill it in, future runs won't overwrite it with null.

---

## 6. Compress a PLY for the web (Phase 5)

```bash
autosplat compress scene.ply --format sog          # ~82 % size reduction
autosplat compress scene.ply --format spz          # ~90 % reduction, fastest
autosplat compress scene.ply --format sog --quality low  # ~91 % reduction, drops SH bands
```

Real-world ratios (bench_chill 19.4 MB → ):

| Format | Quality   | Output | Wall-time |
| ------ | --------- | -----: | --------: |
| SOG    | medium ⭐ |   3.58 MB |   16.1 s |
| SOG    | low (SH=1) | 1.72 MB |    5.1 s |
| SPZ    | medium    |   1.87 MB |    1.3 s |

Backend is PlayCanvas's `splat-transform`, resolved via `npx -y @playcanvas/splat-transform` so no global install is needed — just Node.js. `autosplat doctor` confirms which path it found.

KSPLAT output is not supported by `splat-transform` (only as input). For KSPLAT, use the [mkkellogg/GaussianSplats3D](https://github.com/mkkellogg/GaussianSplats3D) toolchain directly.

Until you've decided on a downstream-tooling stack, the lowest-friction path is **SuperSplat's browser-export to SOG** (no CLI install needed). The `autosplat compress` command is reserved for when you want to scriptable the same conversion.

---

## 7. Manual smoke-test (the workflow Jay runs after a fresh capture)

End-to-end check that a freshly trained PLY makes it all the way to an Obsidian Publish iframe:

1. **Open SuperSplat + load** `~/AutoSplat/outputs/<capture>/scene.ply`
2. **Cleanup** — paint-select floaters, crop bounding box, adjust bloom/colour
3. **Export → SOG** (for size) and **Publish** (for the share URL)
4. **Create Obsidian note** in `3D Memories/` with the SuperSplat share URL as `embed_url:` in the frontmatter (autosplat does this automatically next run if you enable [obsidian] before then)
5. **Sync** to Obsidian Publish if you're using it

See the live Cowork handover for the version with concrete-path / concrete-pixel-coordinates for each step.

---

## 8. Override config for a one-off run

Quick TOML overlay:

```bash
cat >/tmp/lowsteps.toml <<EOF
[brush]
max_steps = 5000
densify_until_iter = 2500
EOF
autosplat process video.mp4 --config /tmp/lowsteps.toml
```

The override layers *on top of* both the packaged defaults and your `~/.config/autosplat/config.toml`. Only the keys you specify are touched.

---

## 9. Re-run a failed capture

If it landed in `state.failed` with reason `interrupted` or `low_camera_ratio`:

```bash
# Re-enqueue manually by name
autosplat process /path/from/state.json/failed/entry
```

If it's a quality-gate failure and you want to bypass the gate just for this run:

```bash
cat >/tmp/no-gate.toml <<EOF
[quality_gate]
enabled = false
EOF
autosplat process video.mp4 --config /tmp/no-gate.toml
```

(Don't do this in the daemon's TOML — you'll burn Brush time on every bad capture.)
