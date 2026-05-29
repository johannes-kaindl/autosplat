# Failure Diagnostics — Design

**Date:** 2026-05-29
**Status:** Approved (autonomous implementation delegated)
**Target release:** v1.8.0

## Problem

A failed capture currently surfaces its cause only as a small `reason` row plus a
40-line raw log tail, while the page header shows a poetic "Signal lost" line.
There's no prominent statement of **when** it failed, a human-readable **why**,
or **what to do** so it doesn't recur. For the Albarella run the user was left
reading raw COLMAP stderr. Per AGENTS.md, pipeline failures must be deterministic
and structured — the data largely exists (`FailedEntry.reason/failed_at/stage`,
`CaptureInfo.reason`); it just isn't classified or shown prominently.

All UI strings are **English** (consistent with the existing WebUI/CLI/docs).
German localization is explicitly out of scope — it would require an i18n
framework across every template and is a separate future project.

## Architecture

**New module `src/autosplat/failure.py` (pure, tested):**

```python
@dataclass
class FailureInfo:
    category: str   # machine key: "blur" | "sfm" | "oom" | "no_video" | "interrupted" | "unknown"
    headline: str   # human one-liner, e.g. "COLMAP couldn't align the frames"
    hint: str       # actionable remediation, e.g. "Rotation-heavy or low-overlap footage — …"

def classify_failure(reason: str | None, stage: str | None = None) -> FailureInfo
```

`classify_failure` matches the persisted `reason` string against an ordered
rules table (first match wins), falling back to a generic entry. Pure and
order-deterministic so it's fully unit-testable and works retroactively on
already-failed captures.

Rules (signature substring → category / headline / hint):

| Signature (case-insensitive) | category | headline | hint |
|---|---|---|---|
| `rejected as blurry` / `blur_threshold` | blur | All frames were too blurry | Footage too soft — use sharper video (slower flight, check focus) or lower `blur_threshold`. |
| `no images with matches` / `failed to create any sparse model` / (`mapper` & `non-zero`) | sfm | COLMAP couldn't align the frames | Rotation-heavy or low-overlap footage — try `autosplat rescue` (auto-bisection) or shoot with more overlap and slower motion. |
| `oom` / `out of memory` / `resolution_cap` | oom | Brush ran out of memory | Lower `resolution_cap` in your config and re-run. |
| `no source video` | no_video | Source video not found | The original video moved or was deleted — re-add it, then resume. |
| `interrupted` | interrupted | The run was interrupted | Sleep, crash, or quit ended it early — click Resume to continue. |
| *(fallback)* | unknown | The run failed | Check the log below for detail, then resume or re-run. |

**Log fallback — `failure_reason_from_log(capture_dir) -> str | None`:** when
`CaptureInfo.reason` is None (old or record-less captures), scan `pipeline.log`
for the last structured `"level": "error"` event and return its `error`/message
field, else the last non-empty line. Keeps every failed capture informative.

## Data flow

`CaptureInfo` already carries `reason`, `finished_at` (= `failed_at` for failed),
and `stage`. The capture-detail route, for `status == "failed"`, computes:

```python
reason = capture.reason or failure_reason_from_log(capture.path)
failure = classify_failure(reason, capture.stage)
```

and passes `failure` + `reason` + `finished_at` to the template. `list_captures`
gains nothing new — it already exposes `reason`/`stage`; the list template
classifies inline via a small Jinja-exposed helper or a precomputed headline.

## WebUI

**Detail page (slice 2):** a prominent failure panel above the stage timeline
for failed captures:

```
⚠  Failed during <stage> · <failed_at>
    <reason — verbatim, monospace>
💡  What to do: <hint>
    [ Resume ]   [ jump to log ]
```

Red-bordered card (`--stage-failed`). Replaces the poetic "Signal lost" line for
failed status (kept for the empty/idle states).

**Captures list (slice 3):** each failed card gets a one-line headline
(`failure.headline`) under the badge so the cause is visible at a glance across
all failed captures — not just on the detail page.

## Error handling

- `classify_failure(None, …)` → fallback entry (never raises).
- `failure_reason_from_log` returns None on missing/unreadable log; the panel
  then shows the fallback headline + "check the log".
- Classification is display-only — it never changes pipeline behaviour or the
  stored `reason`.

## Testing

- **Unit (`failure.py`):** one test per rule signature (blur/sfm/oom/no_video/
  interrupted) + fallback + None input; `failure_reason_from_log` against a
  fixture log with a trailing error event and against a log with none.
- **HTTP:** a failed capture's detail page renders the panel with headline +
  hint + failed_at; a non-failed capture shows no panel; the list shows the
  headline line on a failed card.
- **Real check:** classify the actual Albarella failure reason → expect the
  `blur` (or `sfm`) entry with its hint.

## Out of scope

German / any i18n (separate project); changing pipeline failure behaviour;
CLI output (already prints the error). No new persisted fields — classification
is derived at display time from existing data.
