# Getting Started

A 15-minute path from "I have a drone video and a Mac" to "I have a 3D Gaussian Splat I can open in a browser."

---

## What you need

- **Apple Silicon Mac** (M1 / M2 / M3 / M4 / M5), 16 GB RAM minimum, 32 GB recommended
- **macOS 15+**
- **Homebrew** ([brew.sh](https://brew.sh))
- A drone video — best with **30 fps, sharp, orbit around a textured subject**. See `CONCEPTS.md` for *why* those properties matter.

Not running on Apple Silicon? This pipeline is intentionally Mac-Silicon-only — see spec §2.

---

## Installation

```bash
# 1. Clone the repo
git clone <your-repo-url> /Users/Shared/code/auto-splat-pipeline
cd /Users/Shared/code/auto-splat-pipeline

# 2. System dependencies (Homebrew)
brew install ffmpeg colmap python@3.11 uv

# 3. Download the Brush binary (Rust GS trainer, Mac-native, no CUDA needed)
./scripts/fetch_brush.sh

# 4. Python dependencies (managed by uv)
uv sync

# 5. Preflight — make sure everything resolves
uv run autosplat doctor
```

Expected `doctor` output: all six required rows green (`platform`, `python`, `ffmpeg`, `colmap`, `brush`, `uv`). The `compress` row may show WARN (optional, Phase-5; install Node.js to enable).

If anything is RED: see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

---

## Your first capture

### 1. Pick a good video

If you have a drone arc *around* a textured subject (walking-pace, slow translation, lots of stone/brick/foliage in frame) — perfect. Drop it into `import/` (or any path you remember).

A few things that look like good drone footage but reliably break SfM:
- **Spinning in place** (360° yaw from a fixed point) — no parallax, COLMAP can't triangulate.
- **Abrupt 180°+ turns mid-flight** — even with the exhaustive matcher, loop closure rarely fires.
- **Low-texture surfaces** (snow, sky, water, fresh asphalt, painted walls) — no features for SIFT to lock onto.

If you're not sure, read [`CAPTURE-GUIDE.md`](CAPTURE-GUIDE.md) before you go fly — it's a 5-minute read that saves hours of failed pipeline runs.

### 2. Run the pipeline

```bash
uv run autosplat process import/my-video.mp4
```

What happens:

| Stage | What it does | Typical wall-time |
| ----- | ------------ | -----------------:|
| Preprocess | Extracts ~250 keyframes via ffmpeg, drops blurry ones | 10-30 s |
| COLMAP SfM | Reconstructs camera poses from the frames | 2-15 min |
| Quality-Gate | Bails out if the SfM result is too thin | <1 s |
| Brush training | Trains the 3D Gaussian Splat (30 000 steps default) | 25-50 min |
| Export | Validates the PLY, writes metadata.json | <1 s |
| Viewer | Opens SuperSplat in your browser with the splat loaded | <1 s |

For a 30-second 4K orbit video at default settings: expect **~35-45 min** end-to-end on an M5/32 GB.

### 3. Look at the result

After a successful run:

- The PLY is at `~/AutoSplat/outputs/<capture-name>/scene.ply`
- SuperSplat should have opened automatically in your default browser
- Or you can drag-and-drop the PLY onto <https://playcanvas.com/supersplat/editor>

In SuperSplat: orbit with the left mouse, zoom with scroll. Welcome to your first Gaussian Splat!

---

## Option B: Use the WebUI

If you prefer a browser interface over the terminal, start the WebUI instead:

```bash
uv run autosplat webui --port 8080
# Open http://127.0.0.1:8080 in your browser.
```

From the dashboard:

1. **Dashboard** — see the capture queue, recent runs, and active jobs at a glance.
2. **Captures list** — every capture in your `captures_dir` with its current status badge.
3. **Capture detail** — click a capture to see the stage timeline. Hit **Process** to start a pipeline run.
4. **Live progress** — the stage timeline auto-refreshes every few seconds via HTMX polling.
5. **Cancel** — hit **Cancel** on a running job (useful during the ~40-minute Brush stage).
6. **View** — once a PLY is ready, the **View** button opens the SuperSplat embed directly in the browser.

The CLI (`autosplat process`, `autosplat watch`) continues to work alongside the WebUI — they share the same state file and captures directory.

---

## What's good vs. what's bad

A few minutes after the run finishes, you'll probably see:

- **Main subject**: looks sharp and 3D-real where the drone got close + had good angles
- **Background**: streaky / fuzzy ("floaters") — that's normal, SfM doesn't have great far-distance constraints
- **Behind the orbit**: missing entirely if your orbit was less than 360° — the back side wasn't observed

The Phase-2 manual smoke-test workflow walks through SuperSplat cleanup (paint-select floaters, crop bounding box, publish-share-link, embed in Obsidian). See [`WORKFLOWS.md`](WORKFLOWS.md) §7.

---

## Common adjustments

### Speed it up (lower quality, lower wall-time)

Create `~/.config/autosplat/config.toml`:

```toml
[brush]
max_steps = 5000           # default 30000 — 6× faster, lower density
densify_until_iter = 2500
resolution_cap = 800       # default 1600 — half RAM, half detail
```

Then re-run `autosplat process`. The override layers on top of the packaged defaults.

### Squeeze out more quality (longer wall-time)

```toml
[preprocess]
target_frames = 400
min_frame_distance_sec = 0.05  # allow up to 20 fps

[colmap]
quality = "high"

[brush]
max_steps = 50000
densify_until_iter = 25000
resolution_cap = 2400
```

Total runtime ~1-2 h. Skip this until you've done at least one default run to confirm everything works.

### Enable Obsidian capture-notes

If you keep notes in Obsidian and want every successful run to drop a structured note into your vault:

```toml
[obsidian]
enabled = true
vault_path = "/Users/you/Documents/MyVault"
captures_subdir = "3D Memories"
```

See [`CONFIGURATION.md`](CONFIGURATION.md) `[obsidian]` for all the knobs.

### Compress the PLY for web embedding

After your first successful PLY:

```bash
uv run autosplat compress ~/AutoSplat/outputs/<capture>/scene.ply --format sog
```

Produces a `.sog` next to the `.ply`. ~80 % smaller, loads in any web viewer including SuperSplat. See [`PLY-OUTPUT-FORMAT.md`](PLY-OUTPUT-FORMAT.md) for the format comparison.

---

## Optional shell alias

Run `bash scripts/install_splat_alias.sh` once to add a `splat` shell function to `~/.zshrc`. This lets you call `splat doctor`, `splat watch import/`, `splat serve ... --with-supersplat` from any directory — the function always runs in the repo's own environment.

```bash
bash scripts/install_splat_alias.sh
source ~/.zshrc   # or open a new shell

splat doctor      # verify everything is wired up
```

The function uses a subshell so your working directory is never changed by `splat`.

---

## Next steps

- **Run the watch-folder daemon** for batch workflows: `uv run autosplat watch ~/AutoSplat/inbox`. See [`WORKFLOWS.md`](WORKFLOWS.md).
- **Read `CONCEPTS.md`** to understand what's actually happening at each stage and why some captures work better than others.
- **Read `TROUBLESHOOTING.md`** if your first run hits a snag.

---

## A quick mental model of file locations

```
auto-splat-pipeline/              ← the source code (this repo)
├── config/default.toml           ← all defaults
├── docs/                         ← read these for context
├── src/autosplat/                ← Python modules
└── import/                       ← where YOU drop videos (gitignored)

~/AutoSplat/                      ← runtime output (auto-created)
├── captures/<name>/              ← per-run working dir
│   ├── frames/                   ← extracted JPEGs
│   ├── colmap/sparse/0/          ← SfM cameras + sparse cloud
│   ├── training/                 ← Brush intermediate output
│   ├── output/scene.ply          ← THE result
│   └── pipeline.log              ← structured event log
├── outputs/<name>/scene.ply      ← user-facing copy (same content)
└── inbox/                        ← watch-folder daemon's drop zone

~/.autosplat/state.json           ← watch-folder daemon's queue + history
~/.config/autosplat/config.toml   ← your user-level overrides (optional)
```
