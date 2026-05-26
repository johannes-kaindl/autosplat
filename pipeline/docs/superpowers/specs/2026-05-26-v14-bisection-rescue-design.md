# v1.4 — Auto-Bisection-Rescue · Design

**Status:** approved 2026-05-26 (verbal, autonomous-execution mode)
**Owner:** Johannes Kaindl
**Authoring agent:** Claude Opus 4.7

## Problem

When a video is structurally hostile to SfM (rotation-dominated, 180° turn, 360° spin), the
v1.2.0 adaptive retry already swaps `sequential` → `exhaustive` matcher and bails out with a
helpful `QualityGateFailure` pointing at `docs/CAPTURE-GUIDE.md`. The user's only options
today are: re-shoot, or manually chop the video into pieces and combine them via v1.3.0's
multi-video flow.

The manual case is proven: `max_strasse` (5:35, 180° street drive) failed at ratio 0.02
end-to-end, but when split into 4 hand-cut clips and re-combined via `process v1 v2 v3 v4`,
SfM registered all 865 frames and produced a 1.8 GB scene.ply.

v1.4 automates that work: when the standard adaptive-retry path exhausts itself,
the pipeline performs binary subdivision, probes each leaf clip with a cheap
preprocess+SfM-only run, and combines the surviving leaves through the existing
multi-video pipeline path.

## Goals

- **Auto-eskaliert:** No new CLI command in v1.4. After `sequential`→`exhaustive`→fail,
  the existing `run_pipeline_with_adaptive_retry` calls into the new bisection module
  as a third attempt. The user only sees a longer run.
- **Bounded compute:** Conservative defaults (min-clip 60s, max-depth 3) cap worst-case
  cost at ~8 probe-SfM runs ≈ 30-120 min, before the final combined run.
- **Reuse existing mechanics:** Bisection sits on top of `extract_frames_from_many` and
  the multi-video `run_pipeline` path. The only new pipeline-level capability is the
  cheap probe-SfM and the recursive subdivision algorithm.
- **Honest failure:** When no leaf clip passes the quality-gate, raise
  `QualityGateFailure(reason="bisection_exhausted", retry_hint=None)` — same surface the
  user already understands, with the CAPTURE-GUIDE pointer attached.

## Non-Goals (v1.4)

- **Smart-split at motion-change.** v1.4 splits at midpoint only. Smart-split (detect
  the rotation event with OpenCV optical flow, cut there) is v1.4.1.
- **WebUI per-clip progress.** Bisection runs inside the existing `sfm` stage from the
  state-machine's perspective. Users get structured logs in `pipeline.log` but no
  per-clip progress bar in the WebUI. v1.4.1 candidate.
- **`autosplat rescue` standalone command.** The user's chosen trigger is integrated
  auto-bisect. A standalone command is a v1.4.1 candidate if the auto-path proves clumsy.
- **Cross-video bisection.** Each video in a multi-video capture is treated as one input;
  bisection only fires on the combined-set quality-gate failure, against the *first* video
  of the input list. Multi-video captures that already use bisection-style hand-cuts
  bypass this path entirely (their adaptive-retry succeeds on attempt 1 or 2).

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ run_pipeline_with_adaptive_retry  (pipeline.py)                 │
│                                                                 │
│  attempt 1: sequential matcher    → quality_gate                │
│  attempt 2: exhaustive matcher    → quality_gate                │
│  attempt 3 [NEW]:                                               │
│    if cfg.retry.bisect_enabled and last failure.retry_hint=None │
│      → bisection_mod.rescue_via_bisection(video, capture_dir, …)│
│         (returns PipelineResult or re-raises QualityGateFailure)│
└────────────────────────────┬────────────────────────────────────┘
                             ▼
              ┌─────────────────────────────────┐
              │ src/autosplat/bisection.py      │  NEW
              │                                 │
              │  rescue_via_bisection()         │ top-level orchestrator
              │   ├─ bisect_recursively()       │ pure tree walk (testable w/o ffmpeg)
              │   │   └─ probe_clip()           │ runs preprocess + SfM, returns bool
              │   │       └─ cut_video()        │ ffmpeg subprocess wrapper
              │   │           └─ build_ffmpeg_cut_command()  ⟵ pure string helper
              │   └─ run_pipeline(videos=[…])   │ existing multi-video entry
              └─────────────────────────────────┘
```

### Why a separate module

- `pipeline.py` is already 600 lines. Bisection adds ~250 LOC; keeping it inside would push
  pipeline.py over the threshold where it becomes hard to reason about.
- The recursion + ffmpeg-cut + clip-probe pieces are independently testable. `pipeline.py`
  changes touch only the third-attempt branch in `run_pipeline_with_adaptive_retry`.
- Mirrors the existing module layout pattern (one stage per file: `sfm.py`, `quality.py`,
  `compress.py`).

## Component design

### `src/autosplat/bisection.py`

Public API:

```python
@dataclass(frozen=True)
class BisectionClip:
    """A single sub-clip in the bisection tree.

    `clip_id` is a depth-encoded path: '0', '0_1', '0_1_0'. Used as filename suffix
    and as the probe-workspace directory name so a partial run is debuggable.
    """
    source_video: Path        # the original (untouched) input video
    clip_id: str
    start_s: float
    duration_s: float
    path: Path                # <capture_dir>/rescue/clips/<stem>_part_<clip_id>.mp4


@dataclass(frozen=True)
class BisectionOutcome:
    """Return value of rescue_via_bisection. Always populated; raises on failure."""
    leaves: list[BisectionClip]   # the clips that passed probe_clip
    probed_count: int             # total clips probed (incl. failed ones)
    duration_s: float


def build_ffmpeg_cut_command(
    video: Path,
    start_s: float,
    duration_s: float,
    output: Path,
) -> list[str]: ...
    """Stream-copy ffmpeg command — no re-encode, fast cuts."""


def cut_video(video: Path, start_s: float, duration_s: float, output: Path) -> Path: ...
    """Run the ffmpeg cut. Raises subprocess.CalledProcessError on failure."""


def probe_clip(
    clip: BisectionClip,
    probe_workspace: Path,
    cfg: Config,
) -> bool: ...
    """Run preprocess + SfM against one sub-clip. Returns True if quality-gate passes.

    Uses cfg.colmap.matcher='exhaustive' for probes — sequential is unreliable on
    short segments and we've already spent two attempts on it.

    Probe artifacts (frames/, colmap/) stay on disk under probe_workspace for
    debuggability; the combined final run still re-extracts everything cleanly.
    """


def bisect_recursively(
    source_video: Path,
    duration_s: float,
    capture_dir: Path,
    cfg: Config,
    *,
    depth: int = 0,
    clip_id_prefix: str = "",
    _probe_fn: Callable[[BisectionClip, Path, Config], bool] | None = None,
) -> list[BisectionClip]: ...
    """DFS halt-on-success-per-branch tree walk.

    - Splits the (sub-)video at midpoint into two children.
    - For each child whose duration ≥ cfg.retry.bisect_min_clip_s:
        - cut + probe
        - if probe passes → keep as leaf
        - else if depth+1 < cfg.retry.bisect_max_depth → recurse into that child
        - else → drop (terminal failure on that branch)
    - Returns the flat list of surviving leaves.

    `_probe_fn` injected for testing; defaults to the real probe_clip.
    """


def rescue_via_bisection(
    video: Path,
    capture_dir: Path,
    cfg: Config,
    *,
    state: WatcherState | None = None,
) -> PipelineResult: ...
    """Top-level orchestrator. Called by run_pipeline_with_adaptive_retry.

    1. ffprobe the input video for total duration.
    2. Wipe <capture_dir>/{frames,colmap,training} from the failed attempts.
       (The rescue/ subdir is left intact in case a previous bisection partial-progressed.)
    3. Call bisect_recursively → list of leaf clips on disk.
    4. If no leaves → raise QualityGateFailure(reason="bisection_exhausted", retry_hint=None).
    5. Otherwise: run_pipeline_with_adaptive_retry(videos=[leaf.path for leaf in leaves],
       capture_dir_override=…, _bisection_already_attempted=True) — the multi-video
       path takes over for preprocess+SfM+quality-gate+train+export, with the
       sequential→exhaustive swap still available for the combined set but bisection
       disabled to prevent re-entry.
    """
```

### Changes in `pipeline.py`

`run_pipeline_with_adaptive_retry` gets a third path. The current logic:

```python
while True:
    attempts += 1
    try:
        return run_pipeline(...)
    except QualityGateFailure as e:
        if e.retry_hint is None or attempts >= max_attempts:
            raise           # ← v1.4: intercept here
        ...
```

Becomes:

```python
def run_pipeline_with_adaptive_retry(
    video, config, *, ..., _bisection_already_attempted: bool = False,
):
    bisection_attempted = _bisection_already_attempted
    while True:
        attempts += 1
        try:
            return run_pipeline(...)
        except QualityGateFailure as e:
            if e.retry_hint is None:
                # Exhausted the matcher-swap path. Try bisection if enabled
                # and we haven't already bisected this capture.
                if (config.retry.bisect_enabled
                        and not bisection_attempted
                        and (isinstance(video, Path) or len(video) == 1)):
                    bisection_attempted = True
                    src = video if isinstance(video, Path) else video[0]
                    return bisection_mod.rescue_via_bisection(
                        src, capture_dir, config, state=state,
                    )
                raise
            if attempts >= max_attempts:
                raise
            ...
```

`_bisection_already_attempted` is private (leading underscore) — only used by
`rescue_via_bisection` when it recursively calls the wrapper for the final
combined-multi-video run. Prevents infinite bisection if the combined set also fails.

### Changes in `config.py`

`RetryConfig` gains three fields:

```python
class RetryConfig(BaseModel):
    enabled: bool = True
    max_retries: int = 3
    # v1.4 additions:
    bisect_enabled: bool = Field(
        default=True,
        description="After sequential→exhaustive exhausts, attempt binary subdivision "
                    "of the source video. Disable for fast-fail in CI.",
    )
    bisect_min_clip_s: float = Field(
        default=60.0, ge=10.0, le=600.0,
        description="Sub-clips shorter than this are not probed.",
    )
    bisect_max_depth: int = Field(
        default=3, ge=1, le=6,
        description="Max recursion depth — 3 means up to 8 leaves per video.",
    )
```

`config/default.toml` adds the same three fields under `[retry]` with comments.

## Data flow

### Disk layout

```
<capture_dir>/
├─ frames/                ← final combined frames (after rescue + add_video flow)
├─ colmap/                ← final combined sparse model
├─ training/              ← final brush training
├─ output/scene.ply
├─ pipeline.log           ← multi-video schema: videos: [leaf_1.mp4, leaf_2.mp4, …]
└─ rescue/                ← NEW
   ├─ clips/
   │   ├─ <stem>_part_0.mp4         ← first-level cuts that became leaves
   │   ├─ <stem>_part_1_0.mp4       ← deeper cuts that became leaves
   │   └─ …
   └─ probes/
       ├─ 0/{frames,colmap}         ← probe artifacts for clip_id '0' (failed)
       ├─ 1/{frames,colmap}         ← (passed — but the probe data is still kept)
       └─ …
```

- `rescue/clips/*.mp4` are stream-copied (no re-encode) so cuts are near-instant and
  exact (no keyframe-snapping). The user's source video is never modified.
- `rescue/probes/<clip_id>/` is kept after a successful rescue for debugging the
  decision (which clips passed, which didn't). Cleanup is a manual `rm -rf` for now.

### Structured log events

```
{"event": "bisection.start", "video": "...", "duration_s": 335.0}
{"event": "bisection.cut", "clip_id": "0", "start_s": 0, "duration_s": 167.5, "path": "..."}
{"event": "bisection.probe", "clip_id": "0", "cameras_registered": 4, "ratio": 0.03, "passed": false}
{"event": "bisection.probe", "clip_id": "0_1", "cameras_registered": 78, "ratio": 0.62, "passed": true}
{"event": "bisection.done", "leaves": ["0_1", "1_0"], "probed_count": 5, "duration_s": 1840.0}
{"event": "bisection.combine_start", "leaf_count": 2}
{"event": "pipeline.done", ...}     ← from the final multi-video run_pipeline call
```

These land in `pipeline.log` for later forensic reading; no WebUI integration in v1.4.

## Error handling

| Situation | Behavior |
|---|---|
| ffprobe fails on source video | propagate — pipeline was already broken |
| ffmpeg cut fails for one clip | log warning, treat clip as failed-probe, continue |
| Probe SfM crashes (non-quality-gate exception) | log warning, treat clip as failed-probe |
| Probe quality-gate fails | normal "leaf failed" path (recurse or drop) |
| Zero leaves survive | raise `QualityGateFailure(reason="bisection_exhausted", retry_hint=None)` |
| Combined final run fails quality-gate | bubble up as-is (no second bisection on the same capture) |
| Source video too short (`duration_s < 2 * min_clip_s`) | log warning, raise the original failure unchanged |

The `bisection_attempted` flag in `run_pipeline_with_adaptive_retry` ensures bisection
fires at most once per capture — no infinite recursion if the combined run also fails.

## Testing strategy

Per AGENTS.md: TDD red-first, atomic slices, real-HTTP-tests where applicable. Bisection
has no HTTP surface, so unit tests cover everything except the actual ffmpeg/colmap
subprocess invocations.

### Test markers

- `needs_ffmpeg` — applies to `test_cut_video_actually_runs_ffmpeg`
- `needs_colmap` — applies to `test_probe_clip_end_to_end`
- All other tests are pure-Python with monkeypatched subprocess calls.

### Coverage matrix

| Test | Function | Notes |
|---|---|---|
| `test_build_ffmpeg_cut_command_basic` | `build_ffmpeg_cut_command` | string assertion only |
| `test_build_ffmpeg_cut_command_uses_stream_copy` | same | `-c copy` present, no `-vf` |
| `test_build_ffmpeg_cut_command_clamps_negative_start` | same | start_s=-5 → 0 |
| `test_cut_video_calls_ffmpeg` | `cut_video` | mocked subprocess.run |
| `test_probe_clip_passes_on_good_sfm` | `probe_clip` | monkeypatch extract_frames + run_colmap |
| `test_probe_clip_fails_below_ratio` | `probe_clip` | ratio 0.1 → False |
| `test_probe_clip_propagates_ffmpeg_error` | `probe_clip` | subprocess raises |
| `test_bisect_recursively_keeps_passing_leaf` | `bisect_recursively` | stub probe returns [True, False] |
| `test_bisect_recursively_recurses_on_failed_branch` | same | False→True→True tree |
| `test_bisect_recursively_halts_at_max_depth` | same | All False, depth=2 → empty |
| `test_bisect_recursively_skips_below_min_clip` | same | 30s clip @ min_s=60 → skipped |
| `test_rescue_via_bisection_calls_run_pipeline_with_leaves` | `rescue_via_bisection` | monkeypatch all subprocess + pipeline |
| `test_rescue_via_bisection_raises_when_no_leaves` | same | empty list → QualityGateFailure |
| `test_adaptive_retry_calls_bisection_on_exhausted_hint` | `run_pipeline_with_adaptive_retry` | monkeypatch rescue + force failure |
| `test_adaptive_retry_skips_bisection_when_disabled` | same | bisect_enabled=False → re-raise |
| `test_adaptive_retry_skips_bisection_on_multi_video` | same | len(videos)>1 → re-raise |
| `test_adaptive_retry_fires_bisection_only_once` | same | bisection_attempted flag |
| `test_cut_video_actually_runs_ffmpeg` | `cut_video` | @needs_ffmpeg, real cut |
| `test_probe_clip_end_to_end` | `probe_clip` | @needs_colmap + @needs_ffmpeg |

Total: ~19 new tests. Pre-existing test count ~265 → target ~284.

## Implementation slices (TDD-red-first)

Each slice is a single commit. Each ends ruff-clean, mypy-clean, full pytest-q green.

1. **Slice 0** — `config.py` + `default.toml`: add the three `bisect_*` fields.
   Tests: `test_config.py` extension verifying defaults + validation bounds. ~10 LOC.
2. **Slice 1** — `bisection.py`: `build_ffmpeg_cut_command` + `BisectionClip` dataclass.
   Tests: 3 pure string-assertion tests. ~30 LOC.
3. **Slice 2** — `bisection.py`: `cut_video` (mocked subprocess test).
   Tests: 1 mock-subprocess test. ~20 LOC. Opt-in `needs_ffmpeg` test deferred to slice 8.
4. **Slice 3** — `bisection.py`: `probe_clip` with monkeypatched pipeline calls.
   Tests: 3 tests (pass / fail-ratio / subprocess-raises). ~50 LOC.
5. **Slice 4** — `bisection.py`: `bisect_recursively` recursion.
   Tests: 4 tests (keep / recurse / max-depth / min-clip). ~70 LOC.
6. **Slice 5** — `bisection.py`: `rescue_via_bisection` orchestrator.
   Tests: 2 tests (success-with-leaves / no-leaves). ~50 LOC.
7. **Slice 6** — `pipeline.py`: integration into `run_pipeline_with_adaptive_retry`.
   Tests: 4 tests in `test_pipeline.py` (fires / disabled / multi-video skip / fires-once).
   ~30 LOC.
8. **Slice 7** — opt-in real-binary tests (`needs_ffmpeg`, `needs_colmap`). ~30 LOC.
9. **Slice 8** — docs: `CAPTURE-GUIDE.md` adds a "Bisection" section; CHANGELOG `[Unreleased]`
   entry; `default.toml` comment block. No code.

After slice 8: release prep (commit, tag `v1.4.0`, push to Codeberg, GitHub-mirror updates,
Codeberg release-page body via `gh`-equivalent API call).

## Open questions

None at design time — user authorised autonomous resolution of all remaining detail.

## References

- [`docs/CAPTURE-GUIDE.md`](../../CAPTURE-GUIDE.md) — empirical shoot rules + failure modes
- [`docs/PHASE-0-CALIBRATION.md`](../../PHASE-0-CALIBRATION.md) — `ice_bird` low-texture case
- `e95ccfa` — v1.3.0 multi-video capture commit (the foundation this design builds on)
- Memory `project_max_strasse_showcase` — the 4-clip manual rescue that proved the concept
