# Capture Guide

How to shoot a video that COLMAP can actually solve. The pipeline is only as good as the camera-pose reconstruction at its core — and that step has hard physical requirements the rest of the pipeline can't paper over.

If a capture failed with a `low_camera_ratio` message in the log, **read this first** before re-shooting.

---

## The one rule

> **Adjacent frames must share visible 3D points.**

COLMAP's job is to figure out where the camera was for each frame by triangulating shared feature points across pairs of frames. If consecutive frames have nothing in common — because the camera spun too fast, or the surface had no features, or the lighting changed — the reconstruction graph breaks into disconnected islands and the quality-gate refuses to feed Brush.

Everything below is just consequences of that one rule.

---

## Failure modes seen in the wild

These two patterns have produced ratios of 0.01–0.02 (i.e. ~3 of 250 frames registered) even with the `exhaustive` matcher — they're not pipeline bugs, they're inherent SfM failures.

### Rotation-dominated footage

You can't recover from this with code. A drone spinning in place — or rotating sharply mid-flight — moves the camera's *viewing direction* faster than it moves the camera's *position*. Frame N+1 looks at almost the same scene as frame N but from a wildly different angle. SIFT features that survived the rotation are sparse, and the homography between frames degenerates.

**Concrete failures from v1.2.0 smoke testing:**

| Capture | Length | Motion | sequential | exhaustive | Verdict |
|---|---|---|---|---|---|
| `max_strasse` | 5:35 | drove a street, 180° turn, drove back | 3 / 244 | 5 / 244 | unrecoverable |
| `360max` | 0:56 | 360° spin in place | (skipped) | 3 / 250 | unrecoverable |

The 180° turn case is especially nasty: even though the "going back" segment physically looks at the same world as the "going out" segment, the drone's altitude changes the apparent perspective enough that loop closure rarely fires.

### Low-texture surfaces

Sky, water, fresh snow, painted walls, smooth asphalt — anything where SIFT can't find distinctive corners. The `ice_bird` case in [`PHASE-0-CALIBRATION.md`](PHASE-0-CALIBRATION.md) (4/106 cameras over a snowfield) is the canonical example. Asphalt streets are nearly as bad in practice.

---

## Shoot rules

Do these and your capture is very likely to solve.

### ✅ Translation > rotation

Move the camera *through* the scene, not *around* it from a single point. Walk-throughs and drive-throughs work. Tripod pans don't.

For orbiting a single subject (textured statue, sculpture, building): **walk around it**. Even a slow stationary spin from one tripod position produces ~zero parallax and SfM has nothing to work with.

### ✅ Smooth, slow turns

Curves are fine — abrupt turns are not. Keep angular velocity low enough that any single frame still shares ≥30% of its content with the next frame in the subsampled stream (after the pipeline drops to ~250 frames). For a 60s video, that's about 1 frame per 0.25s of original footage — your turn rate has to be slow enough for that cadence to make sense.

A drone making a wide arc over a textured scene is ideal. A drone yawing in place is the opposite.

### ✅ Lots of overlap

Aim for **80% overlap** between consecutive (pre-subsample) frames in the direction of motion. At 60fps that's automatic for walking pace; it falls apart fast for drone speeds over ~5 m/s near the ground.

### ✅ Textured surfaces

The subject needs feature corners — brick walls, foliage, stones, patterned tiles, weathered concrete. Pure painted surfaces, glossy car bodies, water, and clear sky contribute nothing. Aim the camera so the textured parts dominate the frame.

### ✅ Even, consistent lighting

Sharp shadow boundaries that move between frames look like feature changes to SIFT and confuse matching. Overcast days outperform sunny days for SfM. Avoid mixed sun/shade panning.

### ❌ Don't: 360° spin from a fixed point
### ❌ Don't: abrupt 90°+ turns
### ❌ Don't: capture over textureless surfaces (snow, sky, water, painted walls)
### ❌ Don't: mix bright sun and deep shade in one capture
### ❌ Don't: fly so fast that ground features blur in the subsampled frames

---

## When a capture fails

The pipeline already does what it can on your behalf:

1. **Sequential matcher first** (fast — assumes temporal neighbors share features).
2. **Quality-gate** catches a low camera ratio (default: <50% of frames registered).
3. **Adaptive retry** swaps in the `exhaustive` matcher (every frame against every frame — much slower, much more robust to loops).
4. **Quality-gate again** — if exhaustive still produces <50% registered, the run escalates to auto-bisection (v1.4+).
5. **Auto-bisection (v1.4+)** binary-subdivides the source video and probes each half with a cheap SfM-only run. Surviving halves get recombined through the multi-video pipeline path that proved out on `max_strasse` (4 hand-cut clips → 100 % registered).
6. **Quality-gate one last time** on the combined leaf set — if even that fails, the run aborts before Brush.

What the user sees:

```
WARNING  quality_gate.failed reason="low_camera_ratio: 0.02 < 0.5" matcher=exhaustive retry_hint=null
WARNING  pipeline.bisection_escalation reason="low_camera_ratio: 0.02 < 0.5"
INFO     bisection.start video=… duration_s=335.0
INFO     bisection.probe clip_id=0 cameras_registered=4 ratio=0.03 passed=false
INFO     bisection.probe clip_id=0_1 cameras_registered=78 ratio=0.62 passed=true
…
INFO     bisection.combine_start leaf_count=2
```

If the combined re-run still fails with `retry_hint=null`, **no further automatic recovery is possible** — both the matcher swap and bisection have been tried. At that point:

### Read the camera count

A capture log ends with something like:

```json
{"cameras_registered": 5, "frames_kept": 250, "ratio": 0.0205, ...}
```

- **ratio ≥ 0.5** — the gate would have passed; the failure was something else (read the log).
- **0.1 ≤ ratio < 0.5** — borderline; the capture *might* still be salvageable. Two levers worth trying:
  - More frames: `autosplat process video.mp4 --target-frames 500` (default 250). Helps especially for long videos — a 30-min walkthrough at 250 frames is one frame every 7s, often too sparse.
  - Manually trim the worst segment in ffmpeg and re-run on the shorter clip.
- **ratio < 0.1** — structurally broken. The footage doesn't satisfy the "adjacent frames share 3D points" rule. Re-shoot per the rules above; no parameter tweak will rescue this.

### Resume vs re-shoot

If you fix the *capture* (re-shoot with better motion) — start a fresh `autosplat process` with the new video.

If you fix the *configuration* (e.g. higher fps_target — see [`CONFIGURATION.md`](CONFIGURATION.md)) and want to keep the extracted frames — `autosplat resume <capture_dir>`. The resume command re-uses everything that's on disk; only the stages whose artifacts were invalidated will re-run.

Don't resume after re-shooting — the frames on disk are from the old video. Just `process` the new one.

---

## Auto-bisection internals (v1.4+)

When bisection fires, it materialises three things on disk under the failing capture's directory:

```
<capture_dir>/rescue/
├─ clips/                  ← physical .mp4 sub-clips (stream-copied, no re-encode)
│   ├─ <stem>_part_0.mp4
│   ├─ <stem>_part_1_0.mp4
│   └─ …
└─ probes/                 ← per-clip preprocess+SfM artefacts (kept for forensics)
    ├─ 0/{frames,colmap}
    ├─ 1/{frames,colmap}
    └─ …
```

The `clip_id` (`0`, `0_1`, `0_1_0`) is a depth-encoded path through the bisection tree: a leading `0` is the first half of its parent, a `_1` step is a deeper-level second half, and so on. Probe artefacts stay on disk after a successful rescue so you can inspect *which* sub-clip carried the reconstruction — useful when you want to re-shoot just the broken segment.

Three knobs in `[retry]` of your config control the behaviour:

| Key | Default | Meaning |
|---|---|---|
| `bisect_enabled` | `true` | Master switch. Set to `false` in CI to fast-fail without bisection. |
| `bisect_min_clip_s` | `60.0` | Sub-clips shorter than this are not probed (60 s is roughly the lower bound where SfM can find enough overlap on its own). |
| `bisect_max_depth` | `3` | Recursion cap. Depth 3 means at most 2³ = 8 leaf clips per video — keeps worst-case probe-cost bounded. |

Worst case for a 5-minute video with depth=3 and 60 s min-clip is 8 probes × ~5 min ≈ 30–60 min before the final combined Brush run. Disable bisection if your CI budget can't absorb that.

### Reclaiming disk after a successful rescue

The per-probe `rescue/probes/<clip_id>/` workspaces (frames + COLMAP) stay on disk for forensic debugging — typically **~1-3 GB per capture**. After you've verified the rescue worked, drop them with:

```bash
uv run autosplat cleanup-rescue ~/AutoSplat/captures/<capture-name>
# or, if you also want to drop the leaf .mp4 cuts (resume/add-video won't work anymore):
uv run autosplat cleanup-rescue <capture-dir> --remove-clips
# preview without touching disk:
uv run autosplat cleanup-rescue <capture-dir> --dry-run
```

The `rescue/clips/*.mp4` sub-clips are kept by default because `pipeline.log` references them — `autosplat resume` and `autosplat add-video` re-extract from them.

---

## Reference cases that worked

- **`herkules_brunnen`** (2026-05-22, 1h23m end-to-end, 100% COLMAP): wide arc around a fountain, slow translation, textured stone background. Canonical "shoot like this."
- **`max_strasse` — manual rescue** (2026-05-25, v1.3.0): 5:35 street drive with a 180° turn. Standalone capture registered 5/244 frames; hand-cut into 4 segments and recombined via `autosplat process v1.mp4 v2.mp4 v3.mp4 v4.mp4` → 1.8 GB scene.ply, 865/865 frames registered.
- **`max_strasse` — auto-bisection rescue** (2026-05-27, v1.4.0+): same source video, no manual cutting. `autosplat rescue max_strasse.MP4` ran for 5 h 36 min on an M5: bisection cut the video at midpoint, both halves passed the SfM probe at depth 1 with exhaustive matcher, the combined-set sequential run failed at 14/493 cams (loop-closure across the cut still hard), the adaptive-retry escalation to exhaustive on the combined frame set finally registered **490/493 cameras (99.4 %)** with 368 k SfM points and 2.0 GB scene.ply. This was the first end-to-end success of the v1.4 auto-bisection-rescue against the same failing video v1.2.0 had given up on. See [the fly-through on YouTube](https://www.youtube.com/watch?v=1U-onh-9QNY).

---

## See also

- [`CONCEPTS.md`](CONCEPTS.md) — *why* SfM has these requirements (camera-pose triangulation maths)
- [`CONFIGURATION.md`](CONFIGURATION.md) — `preprocess` and `colmap` settings you can tweak
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — pipeline-side failures unrelated to capture quality
- [`PHASE-0-CALIBRATION.md`](PHASE-0-CALIBRATION.md) — the `ice_bird` low-texture case study
