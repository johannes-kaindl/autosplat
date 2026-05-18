
| Field         | Value                                    |
| ------------- | ---------------------------------------- |
| **As of**     | May 2026                                 |
| **Architect** | Cowork (for Joe Kaindl)                  |
| **Executor**  | Claude Code                              |
| **Target**    | Apple Silicon (M5, 32 GB RAM), macOS 15+ |
| **Status**    | Ready for handoff                        |

-----

## 1. Vision & Scope

### 1.1 Vision

A fully automated local pipeline that takes drone videos (DJI Neo 2 and any other `.mp4`/`.mov`) and, without any further manual intervention, produces trained 3D Gaussian Splats that open directly in SuperSplat for trimming and camera animations.

### 1.2 In Scope

- Watch-folder-based processing (drop in → result out)
- Frame extraction with quality filtering (blur detection)
- Structure-from-Motion via COLMAP
- Gaussian Splat training via **Brush** (Mac-native, no CUDA stack)
- Auto-export as `.ply` for SuperSplat integration
- CLI interface for manual runs and status queries
- TOML-based configuration with sensible defaults
- Structured logging and per-stage validation
- Optional: auto-entry into Obsidian vault (`PARA/Projects/3D-Captures/`)

### 1.3 Out of Scope (Phase 1)

- Cloud rendering / distributed training
- Mesh extraction from splats (future work)
- Multi-capture fusion (multiple videos into one scene)
- Real-time streaming during drone flight
- Windows/Linux support (Mac-only by design)

-----

## 2. Tech Stack & Rationale

### 2.1 Core Decisions

|Component     |Tool                 |Why not the alternative                                                                                            |
|--------------|---------------------|------------------------------------------------------------------------------------------------------------------|
|Preprocessing |FFmpeg               |Industry standard, brew-installable                                                                               |
|SfM           |COLMAP (via Homebrew)|Gold standard, Mac support stable                                                                                 |
|GS Training   |**Brush** (Rust)     |**Not** Nerfstudio — gsplat is CUDA-only and does not run on MPS. Brush uses WebGPU, single binary, Mac-native.   |
|Orchestration |Python 3.11+         |Standard for pipeline glue                                                                                        |
|CLI           |Typer                |Type-hint-driven, modern UX                                                                                       |
|Watch folder  |watchdog             |Most stable cross-platform lib                                                                                    |
|Config        |TOML + Pydantic      |Validation, IDE support                                                                                           |
|Logging       |structlog + Rich     |Structured + readable in the terminal                                                                            |
|Env management|uv                   |Fast, lockfile-based                                                                                              |
|Viewer/Editor |SuperSplat (Web)     |Browser-based, no install needed                                                                                  |

### 2.2 Rejected Options (with rationale)

- **Nerfstudio/splatfacto**: the gsplat library is CUDA-only; the official docs confirm there is no Apple Silicon support for training. The `--machine.device mps` flag exists, but the rasterization kernels do not run on it.
- **OpenSplat**: a solid alternative, but Brush is more actively developed and has better ergonomics for CLI wrapping.
- **msplat**: faster than Brush on the M series, but too spartan for pipeline integration in Phase 1. A candidate for Phase 3+ as a performance upgrade.
- **DJI FlightHub 2** (has had native GS support since Jan 2026): cloud-based, vendor-locked — contradicts the local pipeline vision. Possibly interesting as a comparison benchmark.

-----

## 3. System Architecture

### 3.1 High-Level Flow

```
┌─────────────┐    ┌──────────────┐    ┌──────────┐    ┌────────┐    ┌───────┐    ┌────────────┐
│ Watch-Folder│───>│ Frame-Extract│───>│  COLMAP  │───>│ Brush  │───>│Export │───>│ SuperSplat │
│  *.mp4/mov  │    │   (FFmpeg)   │    │   (SfM)  │    │(Train) │    │ (PLY) │    │  (Browser) │
└─────────────┘    └──────────────┘    └──────────┘    └────────┘    └───────┘    └────────────┘
                          │                  │              │             │
                          └──────────────────┴──────────────┴─────────────┘
                                              │
                                              ▼
                                    ┌─────────────────┐
                                    │ structlog Output│
                                    │ + Obsidian Note │
                                    └─────────────────┘
```

### 3.2 Component Responsibilities

- **`watcher.py`**: watches the input folder, deduplicates, triggers the pipeline per video
- **`preprocess.py`**: FFmpeg wrapper, keyframe extraction with blur filter (Laplacian variance)
- **`sfm.py`**: COLMAP wrapper (feature extraction → matching → mapper)
- **`train.py`**: Brush subprocess wrapper, parses training progress
- **`export.py`**: PLY validation, copy to outputs, metadata JSON
- **`viewer.py`**: local HTTP server + browser-open on the SuperSplat URL
- **`obsidian.py`** (optional): creates an MD note in the vault with capture metadata
- **`cli.py`**: Typer app with commands `process`, `watch`, `status`, `config`, `doctor`

### 3.3 Data Layout (per capture)

```
captures/
└── 2026-05-14_neo2_garden/
    ├── source/
    │   └── original_video.mp4
    ├── frames/
    │   └── frame_*.jpg
    ├── colmap/
    │   ├── database.db
    │   ├── sparse/0/
    │   └── images.txt
    ├── training/
    │   └── (Brush-Output)
    ├── output/
    │   ├── scene.ply
    │   └── metadata.json
    └── pipeline.log
```

-----

## 4. Repository Structure

```
auto-splat-pipeline/
├── README.md
├── LICENSE
├── pyproject.toml          # uv-managed, deps + scripts
├── uv.lock
├── .python-version         # 3.11
├── config/
│   └── default.toml        # Default config, user-overridable
├── src/
│   └── autosplat/
│       ├── __init__.py
│       ├── __main__.py     # python -m autosplat → cli.app()
│       ├── cli.py
│       ├── config.py       # Pydantic models
│       ├── watcher.py
│       ├── preprocess.py
│       ├── sfm.py
│       ├── train.py
│       ├── export.py
│       ├── viewer.py
│       ├── obsidian.py
│       ├── logging.py
│       └── doctor.py       # Preflight checks (brew deps, brush binary)
├── scripts/
│   ├── install_deps.sh     # Brew + brush binary download
│   └── fetch_brush.sh
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   └── tiny_video.mp4  # ~3s, for E2E
│   ├── test_preprocess.py
│   ├── test_sfm.py
│   ├── test_config.py
│   └── test_e2e.py         # marked @pytest.mark.slow
└── docs/
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    └── TROUBLESHOOTING.md
```

-----

## 5. Phase Plan

### Phase 0 — Manual Baseline Run (before CC implementation)

**Owner:** Joe, **Duration:** ~1-2 hours, **Output:** empirical findings

Before CC writes a single line of code, run through it manually once with a typical Neo 2 video:

1. FFmpeg keyframe extraction with various frame counts (100, 200, 300)
2. Run through the COLMAP CLI, measure timings
3. Train with Brush, assess quality
4. Open SuperSplat and subjectively rate the splat quality

**Deliverable:** a short Markdown document with timings, issues and sensible default parameters → feeds into `config/default.toml`.

### Phase 1 — CLI Tool (MVP)

**Owner:** Claude Code, **Acceptance:** see §11.1

- Single-command pipeline: `autosplat process <video>` runs end-to-end
- Sequential stages, each stage idempotent (resumable)
- Structured logging in `pipeline.log` per capture
- TOML config works, defaults sensible

### Phase 2 — Watch-Folder Daemon

- `autosplat watch <folder>` runs as a long-lived process
- Queue-based (sequential processing, no parallel training on the M5)
- Detection: only process completed files (check size stability, not directly on `created`)
- Auto-recovery after crash (status persisted in `~/.autosplat/state.json`)

### Phase 3 — Quality Validation & Retry

- Pre-flight checks: are video length, resolution, FPS plausible?
- Per-stage validation: did COLMAP register enough cameras? (threshold configurable)
- Adaptive retry with changed parameters on failure
- Skipped-frames detection in FFmpeg

### Phase 4 — Obsidian Integration

- Auto-created capture note in `<vault>/PARA/Projects/3D-Captures/`
- Frontmatter with: capture date, source video, frame count, COLMAP stats, training duration, output path
- Embed link to the `.ply` file (via the Obsidian attachment folder)
- Triggered via a `[[Capture-MOC]]` update

-----

## 6. Configuration Spec

`config/default.toml`:

```toml
[paths]
captures_dir = "~/AutoSplat/captures"
watch_folder = "~/AutoSplat/inbox"
brush_binary = "~/AutoSplat/bin/brush"

[preprocess]
target_frames = 250
blur_threshold = 100.0         # Laplacian variance; lower = blurrier filtered out
min_frame_distance_sec = 0.2   # avoid duplicate frames

[colmap]
matcher = "sequential"         # for video-derived frames; "exhaustive" for unordered
quality = "medium"             # presets: low | medium | high (affects feature count)
single_camera = true           # all frames from one drone camera

[brush]
max_steps = 30000
resolution_cap = 1600
sh_degree = 3
densify_until_iter = 15000
extra_args = []                # passthrough for advanced users

[export]
formats = ["ply"]              # future: ["ply", "splat", "spz"]
copy_to_outputs = true
outputs_dir = "~/AutoSplat/outputs"

[viewer]
auto_open = true
local_http_port = 8765
target = "supersplat"          # supersplat | playcanvas | none

[obsidian]
enabled = false                # opt-in
vault_path = "~/Documents/Vault"
captures_subdir = "PARA/Projects/3D-Captures"
attach_ply = false             # PLY files are large, default off

[logging]
level = "INFO"
console = "rich"               # rich | plain
log_to_file = true
```

User override via `~/.config/autosplat/config.toml` (XDG-style) or `--config <path>`.

-----

## 7. CLI Interface Spec

```
autosplat process <video_path>             Run pipeline once on a single video
        [--config PATH]
        [--output-dir PATH]
        [--skip-stage STAGE]               # for resuming partial runs
        [--dry-run]

autosplat watch <folder>                   Start watch-folder daemon
        [--config PATH]
        [--once]                           # process existing files, then exit

autosplat status                           Show queue + last-N runs

autosplat config show                      Print effective config
autosplat config init                      Generate user config from defaults

autosplat doctor                           Preflight: deps, binaries, perms
autosplat version
```

Exit codes: `0` success, `1` user error, `2` pipeline failure, `3` dep missing.

-----

## 8. Dependencies & Setup

### 8.1 System Dependencies (Homebrew)

```bash
brew install ffmpeg colmap python@3.11 uv
```

### 8.2 Brush Binary

Not in Homebrew. The fetch script downloads the appropriate release binary from GitHub (`ArthurBrussee/brush`), places it at `~/AutoSplat/bin/brush`, makes it executable, and versions it in `~/AutoSplat/bin/.brush-version`.

### 8.3 Python Setup (via uv)

```bash
uv sync                # installs from pyproject.toml + uv.lock
uv run autosplat doctor
```

### 8.4 Python Dependencies (pyproject.toml)

```
typer>=0.12
pydantic>=2.7
watchdog>=4.0
structlog>=24.1
rich>=13.7
tomli-w>=1.0   # only for python <3.11
opencv-python>=4.9  # for blur detection
```

Optional (for Phase 4): `python-frontmatter` for Obsidian note generation.

-----

## 9. Error Handling & Logging

### 9.1 Logging Convention

Each capture gets a `pipeline.log` with structured JSON events:

```json
{"ts": "2026-05-14T12:00:00Z", "stage": "preprocess", "event": "frames_extracted", "count": 247, "duration_s": 12.3}
```

Console output via Rich for live progress, JSON for the audit trail.

### 9.2 Failure Modes & Recovery

|Stage     |Common failure modes                         |Recovery                                   |
|----------|---------------------------------------------|-------------------------------------------|
|Preprocess|Corrupt video, missing audio track ignorable |Skip file, log warning                     |
|SfM       |Too few features (e.g. little texture)       |Retry with different COLMAP params; otherwise skip|
|SfM       |<60% cameras registered                      |Retry with `exhaustive` matcher            |
|Training  |Brush binary missing/incompatible            |Halt, doctor hint                          |
|Training  |OOM (RAM)                                    |Retry with `resolution_cap` halved         |
|Export    |PLY file <1MB                                |Treat as failure, no auto-open             |

### 9.3 State Persistence

`~/.autosplat/state.json`:

```json
{
  "queue": ["path/to/video2.mp4"],
  "in_progress": {"path": "video1.mp4", "stage": "training", "started": "..."},
  "completed": [...]
}
```

-----

## 10. Testing Strategy

### 10.1 Unit Tests (fast)

- Config parsing & validation
- FFmpeg command builder (string assertions, no actual ffmpeg)
- Blur-threshold logic with synthetic images
- Watcher logic with fake filesystem events

### 10.2 Integration Tests (medium)

- Real FFmpeg call on the 3s fixture video
- COLMAP on a 20-frame subset (mocked or cached database)

### 10.3 E2E Test (slow, `@pytest.mark.slow`)

- Complete run on `tests/fixtures/tiny_video.mp4`
- Acceptance: PLY file >100KB, COLMAP registers >50% of frames

### 10.4 CI Note

Phase 1 runs locally. CI on GitHub Actions is difficult because of the COLMAP/Brush setup. Not a goal for Phase 1.

-----

## 11. Acceptance Criteria per Phase

### 11.1 Phase 1 (CLI MVP)

- [ ] `autosplat doctor` correctly detects missing deps
- [ ] `autosplat process tests/fixtures/tiny_video.mp4` produces a valid `scene.ply`
- [ ] The pipeline log contains a start/end event with duration per stage
- [ ] Config overrides via CLI work
- [ ] SuperSplat opens after a successful run with the splat loaded
- [ ] Unit tests green, E2E green

### 11.2 Phase 2 (Watcher)

- [ ] `autosplat watch ~/inbox` processes files in drop order
- [ ] The process survives individual capture failures (no hard crash)
- [ ] State file consistent after kill/restart
- [ ] Two files placed one after another in the inbox are processed serially in the correct order

### 11.3 Phase 3 (Quality)

- [ ] With poor footage (test fixture: shaky_dark.mp4) → graceful retry → skip
- [ ] Validation failures end up in the state file with a rationale

### 11.4 Phase 4 (Obsidian)

- [ ] The capture note is created in the configured vault path
- [ ] Frontmatter validates against an Obsidian-Bases-compatible schema (see §13)

-----

## 12. Open Decisions (to clarify before CC start)

1. **Brush versioning**: pin to a specific release tag or always latest? → **Recommendation:** pin to a known-good version in the `.brush-version` file.
2. **Capture naming**: auto-slug from the video filename or timestamp-based? → **Recommendation:** `{date}_{stem}` (e.g. `2026-05-14_neo2_garden`).
3. **Concurrent processing**: truly purely serial on the M5? → **Recommendation:** yes for Phases 1-2. CPU-bound COLMAP + GPU-bound Brush could run in parallel, but the complexity does not justify it in the MVP.
4. **Obsidian vault path**: which one specifically? → Joe specifies it before CC start, otherwise Phase 4 is deferred.
5. **Telemetry / crash reports**: local-only or optionally aggregated? → **Recommendation:** local-only, no ping to the outside.

-----

## 13. Appendix A — Obsidian Capture Note Template (Phase 4)

```markdown
---
type: capture
captured: 2026-05-14
source: /path/to/original.mp4
duration_s: 47
frames_extracted: 247
colmap_cameras_registered: 231
colmap_points: 18432
training_duration_s: 312
output_ply: ~/AutoSplat/outputs/2026-05-14_neo2_garden/scene.ply
quality_score: null
location: null
tags: [3d-capture, gaussian-splat, drone]
---

# {{capture_name}}

> [!info] Auto-generated by autosplat pipeline

## Source
- Video: `{{video_path}}`
- Drone: DJI Neo 2
- Flight notes: 

## Pipeline Stats
{{table_of_stats}}

## Output
- PLY: `{{ply_path}}`
- SuperSplat: [Open in browser]({{supersplat_url}})

## Notes
<!-- Manual notes after review -->
```

Compatible with Obsidian Bases (folder-scoped Base filterable on `type:capture`).

-----

## 14. Appendix B — Recommended CC Working Sequence

1. CC reads this document in full
2. CC creates the repo skeleton (§4) and commits it as the initial commit
3. CC implements in order: `config.py` → `logging.py` → `doctor.py` → `preprocess.py` → `sfm.py` → `train.py` → `export.py` → `viewer.py` → `cli.py`
4. Per module: implement → unit tests → commit
5. E2E test as the last step of Phase 1
6. Status report to the Architect (Cowork) with: what works, which acceptance criteria are met, which are open, which open decisions from §12 are still blocking
7. Stop after Phase 1. Phases 2-4 in separate sessions.

-----

## 15. Out-of-Scope / Future Work (post-MVP)

- Mesh reconstruction from splats (e.g. via SuGaR)
- Multi-video fusion into one scene
- Web UI instead of CLI
- iCloud sync integration for drone footage
- msplat as a performance backend (instead of Brush) for the M series
- Auto-tagging via a vision model (what does the capture show?)
