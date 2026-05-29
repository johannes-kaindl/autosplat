# Multi-Video-Bisection-Rescue — Design

**Status:** approved (brainstorming 2026-05-29)
**Builds on:** [2026-05-26-v14-bisection-rescue-design.md](2026-05-26-v14-bisection-rescue-design.md)
**Target release:** next minor (bundles the unreleased SfM-hint fix `0069b1d`)

## Problem

Auto-Bisection-Rescue (v1.4) only fires for **single-video** captures. When a
multi-video capture exhausts the matcher-swap retry path
(`retry_hint=None`), `run_pipeline_with_adaptive_retry` re-raises instead of
escalating to bisection. The gate (pipeline.py ~631):

```python
and (isinstance(video, Path) or len(video) == 1)
```

The assumption baked into that gate — *"multi-video captures bypass bisection,
the user already provided the cuts"* — is wrong for the common real case:
multi-video is frequently **two independent drone flights of the same subject**
(or footage added later via `add-video`), not hand-cut clips. If the *combined*
frame set fails SfM because one flight contains a rotation-heavy / blurred
segment that fragments the joint COLMAP model, bisecting that flight and
recombining the survivors could rescue the capture. Today that chance is left
on the table.

### What bisection can and cannot fix here

Bisection removes bad **intra-video** sub-segments so the surviving good
segments register. It therefore helps when one flight has an internal bad patch
poisoning the joint model. It does **not** help when each flight registers fine
alone but the two simply don't co-register (too few shared viewpoints) — that is
a cross-video matching problem, not something shorter clips can solve. The
design must fail fast and informatively in that case rather than burn a full
combined re-run on an unchanged input set.

## Approach (chosen)

**Probe-whole, then bisect only the failures.** For each source video:

1. Probe it **whole** (matcher `exhaustive`, full `preprocess.target_frames`).
2. If it passes → keep the whole video as a leaf (its original path).
3. If it fails → `bisect_recursively` that video → its surviving leaves.

Pool all leaves across all videos, then recombine through the existing
multi-video pipeline path with `_bisection_already_attempted=True`.

Rejected alternatives:
- *Bisect every video unconditionally* — wall-time scales with video-count ×
  depth even for videos that aren't the culprit.
- *Per-video attribution from the failed combined model* — needs new
  frame→video mapping logic; YAGNI for the 2-flight common case.

Whole-video probes use the **full** `preprocess.target_frames` (~250), not the
sub-clip probe cap (`bisect_probe_target_frames` ~120). The cheap cap was tuned
for short segments; on a multi-minute flight it would risk a false-fail and
trigger needless bisection. The cost is ~one SfM run per video — acceptable for
the 2-flight common case.

## Architecture

### 1. Routing (pipeline.py)

The `len(video) == 1` sub-clause becomes a **routing decision** rather than a
hard gate. On `retry_hint=None` with `bisect_enabled and not bisection_attempted`:

- single video (`isinstance(video, Path) or len(video) == 1`) →
  `rescue_via_bisection` (**unchanged** — we already know the whole single video
  fails, so no whole-probe; straight to bisect).
- `len(video) > 1` → **new** `rescue_via_bisection_multi(videos, capture_dir, cfg, state=...)`.

The recursion guard `_bisection_already_attempted` is untouched: both
orchestrators recombine with `_bisection_already_attempted=True`, so a failing
combined re-run hits `bisection_attempted=True` at the gate and re-raises. No
new guard state.

### 2. Whole-video probe (bisection.py)

Extend `probe_clip` with an optional `target_frames: int | None = None`
parameter. When `None`, keep today's behaviour (`bisect_probe_target_frames`).
When set, that value overrides `preprocess.target_frames` in the probe config.
A whole-video probe is `probe_clip` on a `BisectionClip` spanning the entire
video (`start_s=0.0`, `duration_s=full`) with
`target_frames=cfg.preprocess.target_frames`.

### 3. Orchestrator: `rescue_via_bisection_multi`

```
rescue_via_bisection_multi(videos, capture_dir, cfg, *, state=None) -> PipelineResult
```

Sequence:

1. `state.update_stage("bisect", detail="multi-video rescue: N videos")`.
2. Wipe stale `frames/`, `colmap/`, `training/` (same as single-video rescue).
3. For each `video[i]`:
   a. ffprobe duration → decides only whether bisection-on-failure is possible:
      a video `< 2 * min_clip_s` is too short to bisect, so on a whole-probe
      failure it contributes nothing (a short flight that fails alone can't be
      rescued by cutting it shorter).
   b. Whole-probe (`target_frames=full`, workspace `rescue/probes/v{i}_whole/`).
      - pass → append `video[i]` (original path) to the pool; record
        `bisected=False` for this video.
      - fail → `bisect_recursively(video[i], …, clip_id_prefix=f"v{i}")` →
        extend pool with its leaf paths; record `bisected=True`.
4. If the pool is empty → raise `QualityGateFailure(reason="bisection_exhausted")`.
5. If **no** video was bisected (every video passed whole → pool == input set) →
   raise `QualityGateFailure(reason="bisection_no_culprit", retry_hint=None)`.
   Re-running an identical just-failed set is pure waste; the failure is a
   cross-video registration problem bisection can't address. The message names
   this explicitly so the failure-diagnosis surfaces it usefully.
6. Otherwise recombine: `run_pipeline_with_adaptive_retry(pool, cfg,
   capture_dir_override=capture_dir, state=state,
   _bisection_already_attempted=True)`.

### 4. Probe-workspace namespacing (collision fix)

`_probe_workspace_for(capture_dir, clip_id)` keys only on `clip_id`, so two
bisected videos would both write to `rescue/probes/0/`. Passing
`clip_id_prefix=f"v{i}"` into `bisect_recursively` namespaces every child:
clip-ids become `v0_0`, `v1_0`, … → probe workspaces `rescue/probes/v0_0/` and
clip files `<stem>_part_v0_0.mp4`. Whole-probe workspaces use
`rescue/probes/v{i}_whole/`. No collisions; partial runs stay forensically
debuggable per video.

## Data flow

```
multi-video capture fails QG (retry_hint=None)
  → pipeline gate: bisect_enabled, not attempted, len(videos) > 1
    → rescue_via_bisection_multi
        per video: whole-probe → keep-whole | bisect_recursively(prefix=vN)
        pool = whole-survivors + bisected leaves
        guard: empty → bisection_exhausted ; unchanged → bisection_no_culprit
        → run_pipeline_with_adaptive_retry(pool, _bisection_already_attempted=True)
            combined run succeeds → PipelineResult
            combined run fails    → gate sees attempted=True → re-raise
```

## Error handling

- Per-video probe failures (subprocess / ffprobe) are caught inside the existing
  `probe_clip` / `bisect_recursively` (treated as "failed", never crash the
  rescue), unchanged.
- Empty pool → `bisection_exhausted` (existing reason, reused).
- No culprit (nothing bisected) → `bisection_no_culprit` (new reason).
- Combined re-run failure → re-raised via the untouched recursion guard.

## Testing (TDD, red first)

Unit (monkeypatched preprocess/SfM, mirroring existing `test_bisection.py`):

1. `probe_clip` honours an explicit `target_frames` override (and still defaults
   to `bisect_probe_target_frames` when omitted).
2. `rescue_via_bisection_multi`: one video passes whole + one fails→bisects →
   pool = [whole_path, leaf paths]; recombine called with
   `_bisection_already_attempted=True`.
3. All videos pass whole → raises `bisection_no_culprit`, no recombine call.
4. No leaves survive anywhere → raises `bisection_exhausted`.
5. Wipes stale `frames/`/`colmap/`/`training/` before recombine.
6. Probe workspaces are namespaced per video (no `rescue/probes/0` collision):
   two bisected videos produce distinct workspace dirs.
7. pipeline.py routing: a multi-video `QualityGateFailure(retry_hint=None)` with
   `bisect_enabled` calls `rescue_via_bisection_multi` (not a re-raise);
   single-video still calls `rescue_via_bisection`.

No new opt-in E2E needed — the v1.4 real-binary tests already cover the
ffmpeg/COLMAP path; the multi orchestrator is pure composition over tested units.

## Out of scope / non-goals

- Per-video registration attribution from the combined model.
- A wall-time budget / max-videos-to-bisect cap (real captures are ~2 videos;
  add a knob only if a real capture proves it necessary — log, don't silently cap).
- Windows/Linux, cloud training, mesh extraction (per AGENTS.md scope boundaries).

## Slices

- **S1** — `probe_clip` gains `target_frames` override (test 1).
- **S2** — `rescue_via_bisection_multi` happy path + recombine (test 2, 5, 6).
- **S3** — guards: `bisection_no_culprit` + `bisection_exhausted` (test 3, 4).
- **S4** — pipeline.py routing weiche (test 7).
- **S5** — docs: CAPTURE-GUIDE + CHANGELOG; bundle SfM-hint fix; release.
