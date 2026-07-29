# Capture Lifecycle & Storage Retention — Design

**Date:** 2026-07-28
**Status:** Approved (brainstorm), pre-implementation
**Scope:** pipeline core (`lifecycle.py` [new], `cleanup.py`, `export.py`, `config.py`,
`cli.py`) + WebUI (`webui/state.py`, `webui/routes/captures.py`, `webui/share_runner.py`,
capture templates)

**Context:** Sub-project 1 of 4 in the *Workflow-Rundumblick* (input → processing →
output → publishing). Sub-projects 2–4 are seeded at the end of this document and get
their own spec each.

## Problem

A capture directory grows without ever shrinking, and nothing in the system decides when
that growth is over. Measured on the maintainer's machine on 2026-07-28:

| Location | Size | Note |
|---|---|---|
| `~/AutoSplat/captures/` | 19 GB | 12 captures |
| `~/AutoSplat/outputs/` | 8,8 GB | 17 folders, **10 of them orphaned** (their capture is gone) |
| `~/AutoSplat/import/` | 154 MB | |

Three distinct defects produce this:

**1. The cleanup misses the biggest consumers.** `cleanup.py:15` declares

```python
INTERMEDIATE_SUBDIRS = ("frames", "colmap", "training")
```

Neither `rescue/` nor `brush_dataset/` is listed. Bisection-rescue leftovers alone account
for **11,2 of the 19 GB**:

- `2026-05-25_max_strasse_rescue/` — 8,1 GB, consisting entirely of a **nested capture
  directory** (`2026-05-25_A_vor1/` with its own `frames/`, `colmap/`, `training/`,
  `output/`), a pre-Phase-9 layout the current cleanup cannot see because it looks for
  `<capture>/frames`, not `<capture>/<nested>/frames`.
- `2026-05-26_max_strasse/rescue/` — 3,1 GB.

The v1.14.3 sweep (31 GB → 19 GB) reclaimed `frames/` and `colmap/` and looked convincing
enough that the gap went unnoticed.

**2. `outputs/` is an unmanaged second copy.** `export.py:109` copies every finished PLY
to `outputs_dir/<capture>/`. Nothing ever removes it — deleting a capture leaves its
`outputs/` folder behind. Ten such orphans exist today.

**3. There is no lifecycle at all.** Capture status is derived by a ~95-line `if/elif`
chain in `webui/state.py:144-239` (JobRunner memory → `runs.jsonl` → filesystem), while
`review_status` (v1.15.0) lives beside it as a second, independent concept
(`webui/state.py:44`). Neither answers the question this design needs answered: *what is
allowed to happen to this capture now?* The CLI does not know about review status at all.

## Goal

Give a capture an explicit, derived lifecycle, and hang retention off it: intermediates
survive exactly as long as the reconstruction's quality is still in question, and are
reclaimed once a human has signed off. Reclaim the existing backlog through an explicit,
previewable command.

## Non-goals (YAGNI)

- **No persistent lifecycle store.** State is derived from the filesystem, never written
  to a new file. This preserves the property that made the v1.15.0 gate correct: a
  rebuilt PLY invalidates everything downstream by mtime alone, with no bookkeeping to
  keep in sync.
- **No deduplication of share bundles.** The unpacked bundle sitting next to its own zip
  (116 MB for the same data twice in `2026-07-10_LGS_PV`) is a publishing concern —
  sub-project 3. Only `share/_tmp/` is reclaimed here.
- **No archival tier / cold storage / external drive support.**
- **No change to how captures are created or how the pipeline runs.**

## Lifecycle model

Five states, all derived from the filesystem:

| State | Derived from | Intermediates |
|---|---|---|
| `running` | live job (JobRunner) or fresh `progress.json` | kept |
| `failed` | last run failed, no PLY | **kept** — diagnosis needs `colmap/` and `rescue/` |
| `done` | PLY exists, no valid review marker | kept — quality unconfirmed |
| `reviewed` | `.review.json` valid against `output/scene.ply` mtime | **reclaimable** |
| `archived` | `reviewed` and nothing reclaimable left | — |

`archived` is not an action anyone performs; it is the observation "already reclaimed".
No capture can therefore sit in a state the filesystem no longer supports.

**Boundary:** `lifecycle.py` does not model `running` or `queued`. Those are volatile
JobRunner facts that no filesystem can answer. The WebUI keeps composing them as it does
today (live job beats filesystem). `lifecycle.py` answers only "what may happen to this
capture" — which is precisely what the CLI is missing.

## Retention rules

**Kept permanently:**
`output/scene.ply` (or `output/scene_reviewed.ply`) · `output/scene.sog` ·
`output/metadata.json` · `output/.review.json` · `runs.jsonl` · `pipeline.log` ·
`progress.json`

**Reclaimed on `done → reviewed`:**
`frames/` · `colmap/` · `training/` · `brush_dataset/` · `rescue/probes/` · `share/_tmp/`

**Correction (implementation, C1): `rescue/` is NOT reclaimed as a whole.** Only
`rescue/probes/` is. `rescue/clips/*.mp4` are kept: for a bisection-rescued capture the most
recent `pipeline.start` in `pipeline.log` records those leaf clips as the capture's source
list (`read_source_video_from_log`), and `add_video` wipes only frames/colmap/training, never
`rescue/`. Deleting them makes `add-video` fail with "cannot extend a capture whose origin is
unknown", recoverable only by re-running bisection (5h36m on the documented `max_strasse`
case) against an original video that may no longer exist. `cleanup-rescue` already kept them
by default; listing `rescue` here would have let four other paths silently override that
safeguard. The probes are where the mass is (3,1 GB of the 3,1 GB `rescue/` total on the real
tree), so the reclaim figure is unaffected.

**Correction (implementation): `training/` IS still written by the current pipeline.** The
claim that it "no longer writes it" is false — `train.py` points Brush's export path at
`capture_dir/"training"` on every run (`pipeline.py` passes it as `output_dir`), which is also
where `brush.stdout.log` lands. It is a live working dir, not merely a legacy leftover, and
belongs in the list for that reason.

`source/` is deliberately **not** on this list. It is empty in every existing capture, so
reclaiming it would free nothing — but writing the rule down now would pre-empt
sub-project 4, which has to decide whether the source video belongs in the capture at all.
Whatever it decides, it can add `source/` here in one line.

**Grace fallback.** A capture that is never reviewed would never be reclaimed. Config key
`[lifecycle] unreviewed_grace_days` (default `30`) bounds this: the captures list warns
from day `grace - 7` ("wird in 7 Tagen aufgeräumt"), and the reclaim runs on the next
WebUI/app start, with a log entry per capture.

**Correction (implementation, I1): "never silent, never unannounced" is only true for the
captures the UI lists**, so the sweep is scoped to exactly those — top-level directories
under `captures_dir` matching `YYYY-MM-DD_<stem>`, enumerated non-recursively, the same set
`webui/state.py` renders and counts the grace period down for (shared helper
`lifecycle.list_capture_dirs`, so the two cannot drift). As first written the sweep
enumerated via `find_capture_dirs` — recursive, no name filter — and so would have reclaimed
the 6,4 GB nested legacy capture the UI never shows, and, since every existing capture is
already past 30 days, most of the backlog on the first launch after the merge. Nested and
non-conforming layouts are left to `migrate-storage`, which previews before it deletes.

## Components

### `lifecycle.py` (new)

```python
LifecycleState = Literal["failed", "done", "reviewed", "archived"]

@dataclass(frozen=True)
class Lifecycle:
    state: LifecycleState
    reclaimable: list[Path]
    reclaimable_bytes: int
    grace_days_left: int | None   # set only in `done`

def inspect(capture_dir: Path, *, now: datetime, grace_days: int) -> Lifecycle: ...
```

Pure, read-only, deterministic. Testable with `tmp_path` — no server, no pipeline, no
external binaries. It absorbs the review-status computation currently in
`webui/state.py:63` (`_review_status`), which that module then imports back.

### `cleanup.py` (becomes the executor only)

- `INTERMEDIATE_SUBDIRS` gains `rescue` and `brush_dataset`; `share/_tmp` is handled as an
  explicit extra target (it is not a top-level subdir of the same shape).
- `prunable_targets()` delegates to `lifecycle.inspect()` so CLI, WebUI and the grace
  sweep cannot hold three different opinions.
- `prune_intermediates()` keeps its signature and its `NotExported` guard.

### `webui/state.py`

`_review_status` and `resolve_publish_ply` move to (or delegate to) `lifecycle.py`.
`CaptureInfo` gains `reclaimable_bytes` and `grace_days_left` for display. The `if/elif`
chain keeps its job-vs-filesystem precedence but consults `lifecycle.inspect()` for the
filesystem half instead of re-deriving it.

### `webui/routes/captures.py`

`review/confirm` (`:440`) and `review/upload` (`:458`) call `prune_intermediates` after
writing the marker — `rmtree` is fast enough to stay in the request. **Guard:** if the
capture has a live job, the marker is written but the prune is skipped (see Error
handling).

### `webui/share_runner.py`

The share job writes its compressed SOG to `output/scene.sog` and assembles the bundle
from there, instead of producing it inside `share/_tmp/` and discarding it. A subsequent
share reuses the existing `output/scene.sog` when it is newer than the publish PLY.

**Why the SOG is produced on first share, not on review:** compression costs minutes.
Paying it for every reviewed capture — including those never shared — is wasted compute.
The retention rule ("keep the SOG, it saves re-compression when sharing again") only
takes effect from the first share onward anyway.

### `export.py` / `config.py`

`export.py:109` no longer copies to `outputs_dir`. `copy_to_outputs` defaults to `false`
and is marked deprecated in `config/default.toml` and `docs/CONFIGURATION.md`; the key
stays readable so existing `~/.config/autosplat/config.toml` files do not fail to load.
`doctor` emits a warning when it is still `true`.

### `cli.py` — `autosplat migrate-storage`

Scans `captures_dir` **recursively for capture signatures** (a directory containing
`output/scene.ply`, or both `frames/` and `colmap/`), so nested legacy layouts are found.
Also inspects `outputs_dir` for duplicated and orphaned folders.

Without flags it prints a table only — path, state, reclaimable bytes, reason. `--apply`
executes. Relaxed rule for the backlog, without which no legacy capture would ever
qualify: **a finished PLY is sufficient; review status is not required.**

**Hard safety rule, above everything else:** a directory containing the only PLY of a
capture is never touched — including when it is named `output` and formally sits inside
an intermediate.

**Verified (implementation, C3): this now holds globally, as written.** It was originally
implemented only in `migrate-storage`, while `cleanup.prune_intermediates` — and therefore
`sweep_expired`, the review-triggered prune and `cleanup-intermediates` — applied no such
filter, so a shape `migrate-storage` protected was destroyed by "Confirm review" or by
waiting 30 days. The predicate lives in `lifecycle.holds_exported_result` and is applied by
`lifecycle.reclaimable_targets`, which every deletion path derives its targets from.
The enclosing target is kept **whole**, abandoned sibling probes included — deleting *around*
a surviving reconstruction is precisely the operation that could destroy it. The signature is
an exported PLY in a sub*directory*; a loose `training/scene.ply` (a Brush checkpoint already
copied to `output/`) and an abandoned probe workspace (`frames/` + `colmap/`, no PLY) are
duplicates/intermediates and stay reclaimable.

## Data flow

```
review/confirm | review/upload
        │  write .review.json  (unchanged, v1.15.0)
        ▼
  lifecycle.inspect()  ──►  state == reviewed, reclaimable = [...]
        │
        ├─ live job?  ──yes──►  skip prune, log, retry on next occasion
        └─ no ──►  cleanup.prune_intermediates()  ──►  state == archived

first share  ──►  compress to output/scene.sog  ──►  bundle assembled from it
later share  ──►  reuse output/scene.sog if newer than publish PLY

WebUI/app start  ──►  background thread: for each `done` capture past grace → prune
```

## Error handling

- **Prune failure does not roll back the review.** If `rmtree` fails (permissions, open
  file), the marker stays valid; the error is logged and surfaced as a notice. Unreclaimed
  space is cosmetic; a discarded review is lost manual work.
- **Idempotent by construction.** Because targets are derived from the filesystem, a
  repeated call simply retries whatever is still present.
- **No prune while a job runs.** `resume` and `add-video` need `colmap/` and `frames/`;
  reclaiming underneath a running job would make it unrecoverable. The route checks the
  JobRunner and defers.
- **Grace sweep never blocks startup.** Background thread, one log line per reclaimed
  capture, failures swallowed after logging.
- **`migrate-storage --apply` isolates per capture.** One failure does not stop the rest;
  a closing report lists reclaimed / skipped / failed.

## Testing

TDD, red first, matching the existing suite (506 tests).

- `lifecycle.inspect` as a table test over `tmp_path` fixtures: one case per state, plus
  marker-older-than-PLY, missing PLY, `scene_reviewed.ply` without a marker, and
  `grace_days_left` boundaries (day 0, day `grace-7`, day `grace`).
- `cleanup`: `rescue/` and `brush_dataset/` are captured — the regression test for the
  current defect — plus idempotence and `NotExported`.
- Routes: `confirm` and `upload` reclaim; and do **not** reclaim while a job is live.
- `migrate-storage`: dry run changes not a single byte (total size compared before and
  after), `--apply` reclaims, and the PLY safety rule holds for a constructed case where
  `output/` sits inside an intermediate.
- A fixture reproducing the **nested legacy layout** (`<capture>/<capture>/frames`) so
  the recursive scan does not regress.

## Config surface

```toml
[lifecycle]
unreviewed_grace_days = 30   # 0 disables the grace sweep entirely

[export]
copy_to_outputs = false      # deprecated — outputs_dir is no longer written
```

## Expected outcome

| | Before | After |
|---|---|---|
| `captures/` | 19 GB | ~9,4 GB |
| `outputs/` | 8,8 GB | ~8 GB (the 10 orphans) |
| total | 27,8 GB | ~17,4 GB |
| Reclaim trigger | manual button | review sign-off, grace-bounded |
| Sources of truth for retention | 3 (cleanup list, WebUI chain, review marker) | 1 (`lifecycle.py`) |

**Correction (maintainer ruling, 2026-07-29): `outputs/ → 0` was wrong, and so was the
total.** Of the 17 `outputs/` folders, 10 are orphaned — their capture directory is gone, so
each is the ONLY surviving copy of that scene. Those are never deleted, no matter how old
they are. Only genuine duplicates are reclaimed: an `outputs/<name>` whose capture still
exists *and* has its own exported `scene.ply`. That leaves roughly 8 GB of orphans standing
(and a name match whose capture never exported is kept on the same grounds). Consolidating
or deleting them is a manual decision, deliberately outside this sub-project.

Itemised, so the number is checkable: 6,4 GB from the nested legacy capture
(`colmap` 3,3 + `frames` 1,3 + `training` 1,8), 3,1 GB from `2026-05-26_max_strasse/rescue`,
plus roughly 0,1 GB of `share/_tmp` leftovers — about **9,6 GB** of the 19.

Not reclaimed, by design: `2026-05-22_max_strasse` (961 MB) and `2026-05-24_360max`
(1,4 GB) hold `frames/` and `colmap/` but produced **no PLY**. They are `failed`, and
`failed` keeps everything — that is the rule working, not a shortfall. Deleting them
outright stays a manual decision.

## Sub-project seeds (Workflow-Rundumblick 2–4)

Each gets its own spec → plan → implementation cycle, in this order.

**2 — Bedienablauf & Zugänge.** CLI, WebUI-in-browser and AutoSplat.app are three doors
to the same FastAPI app (`desktop.py:154` serves `create_app` and shows it in a WKWebView).
Three viewer artifacts overlap: `viewer/` (parked per root `AGENTS.md:18`, yet still
serving the Pages deploy), `embed/` (vendored, zero-external, used by share bundles and
the .app) and SuperSplat (external, drives the review gate). Question: which door is *the*
door, and what happens to the parked one. Builds on the lifecycle states — they are what
any UI can display.

**3 — Publishing-Kette.** Review → share bundle → zip → **manual** upload to jkaindl.de.
A published bundle has no link back to its capture: no revocation, no update after a
rebuild, no list of what is currently public. Plus the storage duplication deliberately
excluded above (unpacked bundle beside its zip). Seed for the upload automation exists at
`seeds/2026-07-11-autosplat-splat-hosting.md` in the sister repo `jkaindl.de`.

**4 — Input-Seite.** Watch folder `inbox/`, `import/`, the WebUI file picker and
`add-video` are four entries with differing behaviour. `source/` is empty in every
existing capture — worth establishing whether that is intent or attrition. Least coupled,
and the retention rule from this spec settles the "does the source video stay?" question
it would otherwise have to answer.
