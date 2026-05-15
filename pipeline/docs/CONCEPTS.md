# Concepts

What this pipeline actually does, and why each stage matters. Reading this once will save you a lot of debugging later.

If you've never used Gaussian-Splatting tooling: read this top to bottom. If you've done a couple of runs and want to know *why* a specific capture works or doesn't: jump to "Why captures fail."

---

## The big picture

You give the pipeline a video. It gives you a **3D Gaussian Splat** — a special kind of 3D scene representation that:

- looks remarkably photorealistic in a browser viewer
- renders in real-time
- is small enough to embed in web pages (after compression)
- comes from a single phone or drone video — no LiDAR, no photogrammetry rig, no fancy gear

The pipeline strings together three existing open-source tools (FFmpeg, COLMAP, Brush) into a single command. You run `autosplat process video.mp4` and ~30 minutes later you have a `.ply` you can open in SuperSplat.

---

## 3D Gaussian Splatting (3DGS)

A 3D-scene representation introduced in [Kerbl et al., SIGGRAPH 2023](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/). Instead of storing a scene as a polygon mesh or a point cloud, you store it as a cloud of **anisotropic 3D Gaussians** — fuzzy ellipsoids with position, rotation, scale, opacity, and view-dependent colour.

When you render the scene, a GPU splats each Gaussian onto the screen as a small soft ellipse. Tens of thousands of these overlapping ellipses combine into something that looks photorealistic at real-time framerates.

Per Gaussian, the standard format stores:

| Field            | Count | What it does                                |
| ---------------- | ----: | ------------------------------------------- |
| Position         |     3 | `(x, y, z)` in world space                  |
| Scale            |     3 | per-axis size of the ellipsoid              |
| Rotation         |     4 | quaternion                                  |
| Opacity          |     1 | how solid vs. translucent                   |
| SH DC term       |     3 | base RGB colour, view-independent           |
| SH higher orders | 0-45  | view-dependent colour (more = more detail)  |

At SH degree 3 (full): 59 floats × 4 bytes = **236 bytes per Gaussian**. A typical splat has 50 k - 1 M Gaussians, so PLYs run from ~10 MB to a few hundred MB. See [`PLY-OUTPUT-FORMAT.md`](PLY-OUTPUT-FORMAT.md) for the full byte-level reference.

---

## Why a video at all?

You don't write a Gaussian Splat by hand. You train it from photos. Specifically:

1. From a set of photos of a static scene from different angles…
2. …a Structure-from-Motion (SfM) algorithm figures out where each camera was…
3. …and an optimiser (Brush) iteratively adjusts a cloud of Gaussians so that, when you render them from those camera positions, the result matches each photo.

A video is just a convenient way to capture "lots of photos from different angles". We extract individual frames as the input photo set.

This means **the quality of your splat is bottlenecked by how cleanly SfM can figure out the camera positions.** That's where most failures come from. Read on.

---

## Stage 0 — Pre-flight (Phase 6)

Before *anything* else runs, `preflight.run_preflight(video)` calls ffprobe on the file:

- **ffprobe-validate**: did ffprobe accept the file at all? If not, raise `PreflightFailure(reason="video_corrupt")` and skip the entire pipeline. Spec §9.2 explicitly calls this out — better to fail in 200 ms than waste 30 minutes downstream.
- **Plausibility**: is the duration between 3 s and 10 min, shortest side ≥720p, fps between 23 and 120? If not, raise `PreflightFailure(reason="implausible_duration"/"implausible_resolution"/"implausible_fps")`.

Thresholds are intentionally wide. They catch obviously-wrong inputs (misclick: 4-minute timelapse, 240×135 thumbnail, 0.5 fps slow-motion source) without rejecting anything reasonable.

## Stage 1 — Preprocess (FFmpeg + blur filter)

FFmpeg extracts ~250 keyframes from the video, spread evenly across its duration. Then a Laplacian-variance filter throws away frames that look too blurry — moving cameras at high shutter speeds produce motion blur, and blurry photos confuse SfM.

**Knobs:** `[preprocess].target_frames`, `min_frame_distance_sec`, `blur_threshold`.

**The blur_threshold trap:** the default of 100 works on slow-pass captures (Phase-0 `bench_chill`: 0 % blur-rejected). On fast 60 fps fly-throughs and continuous orbits, it can reject 88-100 % of frames, leaving the pipeline with nothing. Lower to 25 or 50 for high-motion captures. See `PHASE-0-CALIBRATION.md`.

**Phase 6 — skipped-frames detection:** ffmpeg sometimes drops near-duplicate frames during extraction. Preprocess scans stderr for `skipped: N` / `skipped N frames` patterns and logs WARN when the count exceeds 5 % of `target_frames` — usually harmless, but a flag for stationary "drone hovers" sections.

---

## Stage 2 — Structure-from-Motion (COLMAP)

COLMAP's job: given N photos with no camera info, figure out where each photo was taken from in 3D space.

Three sub-stages:

1. **Feature extraction.** Detect distinctive features in each frame (SIFT corners — areas of high local contrast).
2. **Matching.** For each pair of frames, find which features correspond. Two strategies:
   - `sequential` matcher: only matches each frame with its neighbours in time. Fast, good for video where adjacent frames overlap heavily.
   - `exhaustive` matcher: matches every frame with every other frame. Slow (O(n²)) but more thorough — needed when sequential coverage is too thin.
3. **Mapper.** Solves a giant non-linear system: given the matches, find camera positions and a sparse 3D point cloud that explains them all.

What you want at the end: **cameras_registered ≈ frames_kept** (close to 100 %), and a sparse point cloud with **50 k - 200 k points**.

**SfM fails when:**

- **Frames don't overlap enough** — fast camera motion (60 fps fly-through at speed) means adjacent frames see nearly disjoint parts of the scene. No matches → no camera positions.
- **Scene is texture-poor** — sky, snow, water, smooth painted walls have very few SIFT features. No detectable corners → no matches.
- **Wrong matcher for the motion** — sequential is for video-like overlap; for jumbled multi-angle shots use exhaustive.

The pipeline's Phase-3 **quality-gate** catches this: if cameras_registered/frames_kept < 0.5 (configurable), it raises `QualityGateFailure` before wasting Brush time. If the matcher was sequential, it suggests retry with exhaustive. See [`PHASE-3-RETRY.md`](PHASE-3-RETRY.md).

---

## Stage 3 — Brush (Gaussian-Splat training)

[Brush](https://github.com/ArthurBrussee/brush) is a Rust implementation of 3D-Gaussian-Splatting training. It takes the COLMAP output (camera positions + sparse point cloud) as a starting point and runs an iterative optimisation loop:

1. Initialise a cloud of Gaussians at the COLMAP sparse points.
2. For each iteration:
   - Pick a frame and its COLMAP camera position.
   - Render the current Gaussian cloud from that position.
   - Compare to the actual photo.
   - Compute gradients to adjust each Gaussian (move, rotate, change colour, change opacity).
3. Periodically **densify**: split big Gaussians into smaller ones where the rendering is too coarse, merge or kill ones that aren't contributing.

After 30 000 iterations (the default), you have a Gaussian cloud that renders something very close to the input photos from any of the input camera positions — and reasonably close from nearby positions too.

**Why Brush and not Nerfstudio's gsplat?** gsplat's rasterisation kernels are CUDA-only — they don't run on Apple Silicon's GPU. Brush uses WebGPU, which runs natively on Metal on Mac. See spec §2.2 for the full history.

**Knobs:** `[brush].max_steps` (more = better, slower; default 30 000), `resolution_cap` (input image downsampling; tradeoff between memory and detail), `sh_degree` (0 = ambient colour only, 3 = full view-dependent; default 3), `densify_until_iter` (when to stop adding Gaussians; default 15 000 = half of max_steps).

**Phase 6 — OOM auto-retry:** if Brush's stderr matches an OOM pattern (`out of memory`, `wgpu memory`, `device lost`, …), `BrushOOMError` is raised carrying the attempted `resolution_cap`. The watcher then re-enqueues with `{brush: {resolution_cap: cap // 2}}` (clamped to the Pydantic minimum 256). Spec §9.2 recovery, automated.

**Phase 7 — progress visibility:** Brush v0.3 renders its iteration counter via TUI, not stdout, so we estimate progress from wall-time against a heuristic (`~80 ms/step at resolution_cap=1600`, scales quadratically with resolution). A heartbeat thread fires `progress_callback(elapsed_s, est_pct)` every 2 s. In interactive mode, `pipeline.run_pipeline` wraps the Brush stage in a Rich progress bar that shows elapsed time, percent, and ETA.

---

## Stage 3.5 — Quality-Gate (Phase 3)

A small validation stage that sits between SfM and Brush. It checks:

- `cameras_registered / frames_kept ≥ 0.5` (configurable)
- `points ≥ 5000` (configurable)

If either fails, it raises `QualityGateFailure(reason, retry_hint, metrics)`. The watcher uses the `retry_hint` to retry with an adjusted config — e.g. `{"colmap": {"matcher": "exhaustive"}}` when sequential matcher gave a low camera ratio.

Without the gate, the pipeline would happily train Brush for 30 minutes on a 4-camera SfM result that produces garbage. The gate fails fast and saves the compute. See `docs/PHASE-3-RETRY.md`.

---

## Stage 5 — Export

Validates the Brush-produced PLY (header magic, minimum size), copies it to `output/scene.ply` and `~/AutoSplat/outputs/<capture>/scene.ply`, writes `metadata.json` with the stats. Nothing fancy — just structured handoff.

---

## Stage 6 — Viewer / Obsidian (optional)

If `[viewer].auto_open = true`: starts a tiny local HTTP server, builds a SuperSplat URL that points at it, and opens your default browser.

If `[obsidian].enabled = true`: generates an Obsidian Markdown note in your vault with frontmatter capturing all the stats, an iframe-embed slot for the published SuperSplat URL, and a marker-protected region for your own notes that survives re-runs.

**Phase 8** also preserves user-added frontmatter keys across re-runs — add `location:`, `weather:`, or any other key and it stays put.

---

## Stage 7 — Compress (Phase 5, optional)

If `[compress].enabled = true`: produces compressed splat formats next to the canonical PLY.

- **SOG** (PlayCanvas Self-Organizing-Gaussians): ~82 % size reduction, SuperSplat-native loader
- **SPZ** (Niantic): ~90 % size reduction, even smaller and faster than SOG, but narrower viewer compatibility
- **KSPLAT** (Three.js GaussianSplats3D): not currently wired in (would need the mkkellogg toolchain)

See [`PLY-OUTPUT-FORMAT.md`](PLY-OUTPUT-FORMAT.md) for measured ratios and a format-selection guide.

---

## Why captures fail

The pipeline can produce a great splat or a useless one depending on your input. Here's the diagnosis tree:

```
"Pipeline didn't even start"
├── PreflightFailure: video_corrupt
│   └── Re-export the video (`ffprobe -v error -i <video>` shows the underlying error)
├── PreflightFailure: implausible_duration / resolution / fps
│   └── Source is outside Phase-6 plausibility bounds. Trim / upscale / recapture.
└── (Phase 6 catches both before any extraction time is wasted)

"Pipeline ran but the splat looks bad"
├── Most frames were rejected by blur filter
│   └── Lower blur_threshold (try 25 or 50)
├── COLMAP registered < 50 % of frames
│   ├── Was the matcher "sequential"?
│   │   └── Quality-gate auto-retries with matcher="exhaustive" (Phase 3)
│   ├── Is the scene texture-poor (sky/snow/water)?
│   │   └── Recapture with more ground detail / variation
│   └── Is the source 60 fps fly-through?
│       └── Recapture at 30 fps with more parallax per frame
├── Brush OOM during training
│   └── Auto-retried with resolution_cap // 2 by the watcher (Phase 6)
├── Training ran but the splat has many floaters
│   └── Expected for short/limited-angle captures. Use SuperSplat to clean up manually.
└── Training ran but the splat is missing one side
    └── Your orbit didn't cover that side. Either accept it or recapture with full 360°.
```

The single highest-leverage thing you can change is the **capture itself**. A great splat from a bad video is impossible; a usable splat from a great video is almost automatic. See [`GETTING-STARTED.md`](GETTING-STARTED.md) "What you need" and [`PHASE-0-CALIBRATION.md`](PHASE-0-CALIBRATION.md) for the case studies.

---

## What the spec calls each thing

The authoritative spec ([`docs/AUTO-SPLAT PIPELINE — Spec & Implementation Plan.md`](AUTO-SPLAT%20PIPELINE%20%E2%80%94%20Spec%20%26%20Implementation%20Plan.md)) uses some specific terms:

| Spec term         | What it means                                                                |
| ----------------- | ---------------------------------------------------------------------------- |
| Capture           | One run of the pipeline on one video. Produces one capture-dir.              |
| Capture-dir       | `~/AutoSplat/captures/<date>_<video-stem>/` — all artefacts from one run.    |
| Stage             | One step in the pipeline (preprocess, sfm, train, export, …).                |
| Quality-Gate      | Phase-3 stage that validates SfM output before Brush runs.                   |
| Watch-folder      | A directory the daemon watches for new videos to enqueue.                    |
| state.json        | The watch-folder daemon's persistent queue + history.                        |
| Retry-hint        | Config override (like `matcher=exhaustive`) attached to a failure.           |

Once you've internalised these, the rest of the docs read like assembly instructions for something you already understand.
