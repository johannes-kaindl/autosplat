# v1.5.0 — Train-till-Plateau · Design

**Status:** approved 2026-05-27 (verbal, after stdout-discovery probe)
**Owner:** Johannes Kaindl
**Authoring agent:** Claude Opus 4.7

## Problem

Brush trains for `--total-steps` (default 30 000) regardless of whether the
splat has already converged. For typical drone captures the PSNR-vs-steps
curve flattens out before step 30 000 — the remaining ~30-50 % of training
time produces minimal quality improvement.

v1.5.0 adds an opt-in *patience-stop* mechanism: hold out ~10 % of frames,
periodically evaluate PSNR against them during training, and send SIGTERM
to Brush when the curve flattens. The most-recent Brush-exported checkpoint
becomes the final PLY.

## Goals

- **Opt-in.** `[brush] plateau_enabled = false` by default in v1.5.0. The
  feature ships as proof-of-concept; default-on after real-world validation.
- **Reuse Brush's own eval mechanism.** Brush already supports
  `--eval-split-every N` (every-Nth-image holdout) and
  `--eval-save-to-disk` (rendered eval images per checkpoint). We parse
  those rendered PNGs; we don't reimplement holdout selection.
- **No upstream changes to Brush.** Pure subprocess + filesystem
  observation. SIGTERM-and-grab-newest-PLY for the stop mechanism.
- **Honest failure.** If PSNR computation fails for any reason
  (cv2 errors, file race), the monitor logs and continues — never crashes
  the training run. Plateau detection is opt-in optimisation, not load-
  bearing pipeline behaviour.

## Non-Goals (v1.5.0)

- **Auto-tuning of patience/ε.** Sensible defaults shipped; the user
  edits config for now. Adaptive patience can be v1.5.x.
- **Train-resume after plateau-stop.** When SIGTERM fires, training is
  done — we don't add an "actually keep training a bit more" path.
- **Quality scoring of the final PLY.** PSNR plateau is the only stop
  signal; no SSIM, LPIPS, or perceptual metric. Adding others is v1.5.x.
- **Plateau-stop for the `360max` / structurally-broken capture path.**
  v1.4 auto-bisection-rescue handles structural failures; plateau-stop
  assumes the SfM stage already succeeded.

## Discovery findings

A 250-step Brush probe against `max_strasse/brush_dataset` revealed:

1. **Brush emits no stdout/stderr in subprocess mode** — the TUI renderer
   is suppressed when not on a TTY. `subprocess.PIPE` capture gets zero
   bytes. So *stdout parsing of PSNR is not viable.*
2. **`--eval-save-to-disk` is reliable.** Brush writes `eval_<step>/<orig_filename>.png`
   for every held-out frame at each eval checkpoint. The filename matches
   the original frame in `frames/`, so we can pair render-vs-original
   trivially.
3. **`--eval-split-every N` deterministically picks every Nth frame** as
   the eval set. With our `<stem>_frame_NNNNN.jpg` naming (multi-video
   captures included), the picks are temporally uniform.

These three findings drive the design: filesystem-watch eval_<step>/
dirs, compute PSNR ourselves, decide stop ourselves, SIGTERM Brush.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ run_brush()  (existing — train.py)                              │
│                                                                 │
│  if cfg.plateau_enabled:                                        │
│    - extra Brush args: --eval-split-every N --eval-every M      │
│                        --eval-save-to-disk --export-every M     │
│                        --export-name scene.ply  (single file,   │
│                        Brush overwrites — disk stays O(1))      │
│    - spawn PlateauMonitor thread before Brush.subprocess.Popen  │
│    - on monitor → plateau detected: subprocess.terminate()      │
│    - final PLY = the last successfully-exported scene.ply       │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
              ┌─────────────────────────────────┐
              │ train.PlateauMonitor  (NEW)     │
              │                                 │
              │  Thread loop (poll every 5 s):  │
              │   ├─ Scan output/eval_<N>/ dirs │
              │   ├─ For new step N:            │
              │   │   compute_eval_psnr(N) →    │
              │   │   mean across holdout       │
              │   ├─ Append (step, psnr) to     │
              │   │   history; log train.eval   │
              │   └─ Plateau? → set stop event  │
              └─────────────────────────────────┘
                             ▼
              ┌─────────────────────────────────┐
              │ train.compute_eval_psnr  (NEW)  │
              │                                 │
              │  Pure helper:                   │
              │   for each render in eval_<N>:  │
              │     load render                 │
              │     find matching original      │
              │     downscale orig to render res│
              │     mse = mean((a-b)**2)        │
              │     psnr = 10·log10(255²/mse)   │
              │   return mean(psnrs)            │
              └─────────────────────────────────┘
```

### Why a separate monitor thread + helper

- `compute_eval_psnr` is pure cv2 math, fully unit-testable with synthetic
  ndarrays — no Brush, no filesystem.
- `PlateauMonitor` is pure logic over a `list[(step, psnr)]` history and a
  threshold — fully unit-testable by injecting fake PSNR sequences.
- `run_brush` just wires the two: Brush subprocess + monitor thread +
  SIGTERM. The integration is small; the logic that decides "is this a
  plateau?" lives in testable helpers.

## Component design

### `train.compute_eval_psnr(eval_dir: Path, frames_dir: Path) -> float | None`

```python
def compute_eval_psnr(eval_dir: Path, frames_dir: Path) -> float | None:
    """Mean PSNR across all rendered eval images vs their originals.

    Pairs `eval_dir/<name>.png` with `frames_dir/<name>.jpg` by filename
    stem (Brush mirrors original filenames into eval renders).

    Returns None when no pairs are found or all pairs fail to load —
    `PlateauMonitor` treats None as "eval step incomplete, skip".

    Originals are downscaled to the render resolution before MSE so the
    comparison is at the resolution Brush actually trains at (cfg.brush.
    resolution_cap). PSNR uses the standard 8-bit formula
    `10 · log10(255² / mse)`.
    """
```

### `train.PlateauMonitor`

```python
class PlateauMonitor:
    """Polls eval_<step>/ dirs and decides when to stop training.

    Stops when the last `patience` PSNR differences are all below
    `min_delta_psnr`, *and* `min_steps` has elapsed. Records full
    history for forensic logging in `train.eval` events.
    """

    def __init__(
        self,
        output_dir: Path,
        frames_dir: Path,
        min_steps: int,
        patience: int,
        min_delta_psnr: float,
        psnr_fn: Callable[[Path, Path], float | None] = compute_eval_psnr,
    ): ...

    def poll_once(self) -> None:
        """Scan for new eval_<step>/ dirs, compute PSNR, update history,
        check plateau condition. Idempotent — re-running on the same
        state is a no-op."""

    @property
    def should_stop(self) -> bool: ...

    @property
    def history(self) -> list[tuple[int, float]]: ...
```

### Integration in `run_brush`

```python
# At the start, when cfg.plateau_enabled:
monitor = PlateauMonitor(
    output_dir=output_dir,
    frames_dir=frames_dir,
    min_steps=cfg.plateau_min_steps,
    patience=cfg.plateau_patience,
    min_delta_psnr=cfg.plateau_min_delta_psnr,
)

# Existing heartbeat thread; we add a sibling monitor thread:
def _monitor_loop() -> None:
    while not stop_event.wait(5.0):  # every 5 s
        try:
            monitor.poll_once()
        except Exception as e:  # noqa: BLE001 — never crash training
            logger.warning("train.plateau_poll_failed", error=str(e))
            continue
        if monitor.should_stop:
            logger.warning(
                "train.plateau_detected",
                history=monitor.history,
                triggering_at_step=monitor.history[-1][0],
            )
            proc.terminate()  # SIGTERM
            break

# After proc.wait(): newest scene.ply in output_dir is the final result.
# Brush's --export-name=scene.ply (single file, overwritten on each
# export) means disk stays O(1) regardless of how many eval checkpoints
# fired.
```

## Data flow

### Brush args added when plateau_enabled

```
--eval-split-every <cfg.plateau_eval_split_every>   # 10 (10 % holdout)
--eval-every <cfg.plateau_eval_every>               # 1000 steps
--eval-save-to-disk
--export-every <cfg.plateau_eval_every>             # tied to eval-every — every checkpoint
                                                     #  is also a fresh PLY
```

`--total-steps` stays at `cfg.max_steps` (default 30 000) — the SIGTERM
mechanism stops earlier when plateau triggers; otherwise training runs to
completion as today.

### On-disk layout during training (plateau path)

```
<capture_dir>/training/
├─ scene.ply              ← overwritten every eval_every steps; final
├─ eval_1000/
│   ├─ <stem>_frame_00051.png   ← rendered by Brush at step 1000
│   ├─ <stem>_frame_00131.png
│   └─ … (10 % of frames)
├─ eval_2000/
├─ eval_3000/
└─ …
```

### Structured log events

```
{"event": "train.eval", "step": 1000, "psnr": 22.4, "n_pairs": 25}
{"event": "train.eval", "step": 2000, "psnr": 25.1, "n_pairs": 25}
{"event": "train.eval", "step": 3000, "psnr": 26.8, "n_pairs": 25}
{"event": "train.eval", "step": 4000, "psnr": 27.2, "n_pairs": 25}  ← Δ=0.4
{"event": "train.eval", "step": 5000, "psnr": 27.3, "n_pairs": 25}  ← Δ=0.1
{"event": "train.eval", "step": 6000, "psnr": 27.34, "n_pairs": 25} ← Δ=0.04 < 0.05
{"event": "train.eval", "step": 7000, "psnr": 27.37, "n_pairs": 25} ← Δ=0.03 < 0.05
{"event": "train.eval", "step": 8000, "psnr": 27.4, "n_pairs": 25}  ← Δ=0.03 < 0.05 → STOP
{"event": "train.plateau_detected", "triggering_at_step": 8000, "history": [...]}
```

Total steps run: 8 000 instead of 30 000 → ~73 % time saved on a
gut-konvergierenden Capture.

## Error handling

| Situation | Behavior |
|---|---|
| `cv2.imread` returns None on a single eval image | log warning, skip that pair, average remaining |
| All eval images fail to load for a step | `compute_eval_psnr` returns None; monitor treats it as "step incomplete", skips |
| Original frame matching an eval render can't be found | log warning, skip pair |
| `PlateauMonitor.poll_once` raises any exception | logged as `train.plateau_poll_failed`, monitor continues — never aborts training |
| `subprocess.terminate()` doesn't stop Brush within 30 s | the existing run_brush wait-loop handles it; `proc.kill()` fallback already in place via standard Popen semantics |
| Newest `scene.ply` missing after SIGTERM | raise `RuntimeError("Brush terminated before any checkpoint was written")` — surfaces in CLI / WebUI like any other train-failure |
| `plateau_enabled=true` but `min_steps > max_steps` | config validation rejects at load-time (Pydantic validator) |

## Testing strategy

### Unit tests (no Brush, no filesystem races)

| Test | Function | Notes |
|---|---|---|
| `test_compute_eval_psnr_identical_returns_inf_or_high` | `compute_eval_psnr` | synthetic identical images → ∞-ish |
| `test_compute_eval_psnr_known_mse` | same | crafted images with known MSE → matches formula |
| `test_compute_eval_psnr_resolution_mismatch_downscales` | same | render 400×400, original 1600×1600 → still pairs |
| `test_compute_eval_psnr_no_pairs_returns_none` | same | empty eval_dir → None |
| `test_plateau_monitor_no_stop_below_min_steps` | `PlateauMonitor` | inject psnr=very flat at step=1000 < min_steps=5000 → no stop |
| `test_plateau_monitor_no_stop_with_improving_psnr` | same | strictly increasing PSNR over patience window → no stop |
| `test_plateau_monitor_stops_on_flat_history` | same | M consecutive Δ < ε past min_steps → should_stop True |
| `test_plateau_monitor_records_history` | same | poll_once 3× → history has 3 entries |
| `test_plateau_monitor_poll_once_handles_missing_dirs` | same | output_dir empty → no-op, no exception |
| `test_brush_config_plateau_min_steps_ge_validator` | `BrushConfig` | min_steps > max_steps → ValidationError |

Total: ~10 new tests.

### Integration test (manual, opt-in)

`AUTOSPLAT_PLATEAU_E2E=1` would run a 5 000-step training with plateau_enabled
against the existing max_strasse dataset. Asserts: monitor.history non-empty,
final scene.ply exists, training duration < max_steps · ms_per_step (i.e. it
actually stopped early). Not in the unit-test default suite — too slow,
needs Brush.

## Implementation slices

1. **Slice 1** — `config.py`: `BrushConfig.plateau_*` fields + default.toml.
   Tests in `test_config.py`. ~30 LOC.
2. **Slice 2** — `train.py`: `compute_eval_psnr(eval_dir, frames_dir)` pure
   helper + 4 tests. ~50 LOC.
3. **Slice 3** — `train.py`: `PlateauMonitor` class + 5 tests. ~80 LOC.
4. **Slice 4** — `train.py`: integrate monitor thread into `run_brush`;
   extend `build_brush_command` to emit eval flags when plateau_enabled.
   ~40 LOC + 2 integration tests with mocked subprocess/monitor.
5. **Slice 5** — CHANGELOG, CONFIGURATION.md, version bump, push, tag,
   Codeberg release page.

## Open questions

None at design time.

## References

- [`docs/superpowers/specs/2026-05-26-v14-bisection-rescue-design.md`](2026-05-26-v14-bisection-rescue-design.md) — analogous spec, same template.
- Memory `project_roadmap_post_v130.md` — original v1.5 scope mentioned.
- `src/autosplat/train.py` (Brush wrapper, pre-v1.5).
