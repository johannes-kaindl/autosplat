
| Feld          | Wert                                     |
| ------------- | ---------------------------------------- |
| **Stand**     | Mai 2026                                 |
| **Architect** | Cowork (für Joe Kaindl)                  |
| **Executor**  | Claude Code                              |
| **Target**    | Apple Silicon (M5, 32 GB RAM), macOS 15+ |
| **Status**    | Ready for handoff                        |

-----

## 1. Vision & Scope

### 1.1 Vision

Eine vollautomatisierte lokale Pipeline, die Drohnen-Videos (DJI Neo 2 und beliebige andere `.mp4`/`.mov`) entgegennimmt und ohne weiteren manuellen Eingriff trainierte 3D Gaussian Splats produziert, die direkt in SuperSplat zum Trimmen und für Kamera-Animationen geöffnet werden.

### 1.2 In Scope

- Watch-Folder-basierte Verarbeitung (drop in → result out)
- Frame-Extraktion mit Quality-Filtering (Blur Detection)
- Structure-from-Motion via COLMAP
- Gaussian Splat Training via **Brush** (Mac-nativ, kein CUDA-Stack)
- Auto-Export als `.ply` für SuperSplat-Integration
- CLI-Interface für manuelle Runs und Status-Queries
- TOML-basierte Konfiguration mit sinnvollen Defaults
- Strukturiertes Logging und Per-Stage-Validation
- Optional: Auto-Eintrag in Obsidian-Vault (`PARA/Projects/3D-Captures/`)

### 1.3 Out of Scope (Phase 1)

- Cloud-Rendering / Distributed Training
- Mesh-Extraktion aus Splats (Future Work)
- Multi-Capture-Fusion (mehrere Videos zu einer Szene)
- Echtzeit-Streaming während Drohnenflug
- Windows/Linux-Support (Mac-only by design)

-----

## 2. Tech-Stack & Rationale

### 2.1 Kern-Entscheidungen

|Komponente    |Tool                 |Warum nicht Alternative                                                                                           |
|--------------|---------------------|------------------------------------------------------------------------------------------------------------------|
|Preprocessing |FFmpeg               |Industriestandard, brew-installable                                                                               |
|SfM           |COLMAP (via Homebrew)|Goldstandard, Mac-Support stabil                                                                                  |
|GS Training   |**Brush** (Rust)     |**Nicht** Nerfstudio — gsplat ist CUDA-only und läuft nicht auf MPS. Brush nutzt WebGPU, single binary, Mac-nativ.|
|Orchestrierung|Python 3.11+         |Standard für Pipeline-Glue                                                                                        |
|CLI           |Typer                |Type-hint-driven, moderne UX                                                                                      |
|Watch-Folder  |watchdog             |Stabilste Cross-platform-Lib                                                                                      |
|Config        |TOML + Pydantic      |Validierung, IDE-Support                                                                                          |
|Logging       |structlog + Rich     |Strukturiert + lesbar im Terminal                                                                                 |
|Env-Management|uv                   |Schnell, lockfile-basiert                                                                                         |
|Viewer/Editor |SuperSplat (Web)     |Browser-based, kein Install nötig                                                                                 |

### 2.2 Verworfene Optionen (mit Begründung)

- **Nerfstudio/splatfacto**: gsplat-Library ist CUDA-only; offizielle Doku bestätigt: keine Apple-Silicon-Unterstützung für Training. Der `--machine.device mps`-Flag existiert, aber die Rasterization-Kernels laufen nicht darauf.
- **OpenSplat**: Solide Alternative, aber Brush ist aktiver entwickelt und hat bessere Ergonomie für CLI-Wrapping.
- **msplat**: Schneller als Brush auf M-Serie, aber zu spartanisch für Pipeline-Integration in Phase 1. Kandidat für Phase 3+ als Performance-Upgrade.
- **DJI FlightHub 2** (hat seit Jan 2026 native GS-Unterstützung): Cloud-basiert, vendor-locked — widerspricht der lokalen Pipeline-Vision. Ggf. als Vergleichs-Benchmark interessant.

-----

## 3. System-Architektur

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

### 3.2 Komponenten-Verantwortlichkeiten

- **`watcher.py`**: Beobachtet Input-Folder, deduplicated, triggert Pipeline pro Video
- **`preprocess.py`**: FFmpeg-Wrapper, Keyframe-Extraktion mit Blur-Filter (Laplacian Variance)
- **`sfm.py`**: COLMAP-Wrapper (Feature extraction → Matching → Mapper)
- **`train.py`**: Brush-Subprocess-Wrapper, parsed Training-Progress
- **`export.py`**: PLY-Validierung, Kopie nach Outputs, Metadaten-JSON
- **`viewer.py`**: Lokaler HTTP-Server + Browser-Open auf SuperSplat-URL
- **`obsidian.py`** (optional): Erstellt MD-Note im Vault mit Capture-Metadaten
- **`cli.py`**: Typer-App mit Commands `process`, `watch`, `status`, `config`, `doctor`

### 3.3 Daten-Layout (pro Capture)

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

## 4. Repository-Struktur

```
auto-splat-pipeline/
├── README.md
├── LICENSE
├── pyproject.toml          # uv-managed, deps + scripts
├── uv.lock
├── .python-version         # 3.11
├── config/
│   └── default.toml        # Default-Config, vom User überschreibbar
├── src/
│   └── autosplat/
│       ├── __init__.py
│       ├── __main__.py     # python -m autosplat → cli.app()
│       ├── cli.py
│       ├── config.py       # Pydantic-Models
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
│   │   └── tiny_video.mp4  # ~3s, für E2E
│   ├── test_preprocess.py
│   ├── test_sfm.py
│   ├── test_config.py
│   └── test_e2e.py         # markiert @pytest.mark.slow
└── docs/
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    └── TROUBLESHOOTING.md
```

-----

## 5. Phasenplan

### Phase 0 — Manueller Baseline-Run (vor CC-Implementation)

**Owner:** Joe, **Dauer:** ~1-2 Stunden, **Output:** Erfahrungswerte

Bevor CC eine Zeile Code schreibt, einmal manuell durchspielen mit einem typischen Neo-2-Video:

1. FFmpeg-Keyframe-Extraktion mit verschiedenen Frame-Counts (100, 200, 300)
2. COLMAP CLI durchlaufen, Zeiten messen
3. Brush trainieren, Quality bewerten
4. SuperSplat öffnen und Splat-Qualität subjektiv einordnen

**Deliverable:** Kurzes Markdown mit Timings, Issues und sinnvollen Default-Parametern → fließt in `config/default.toml` ein.

### Phase 1 — CLI-Tool (MVP)

**Owner:** Claude Code, **Acceptance:** s. §11.1

- Single-Command-Pipeline: `autosplat process <video>` läuft End-to-End
- Sequenzielle Stages, jeder Stage idempotent (wiederaufnehmbar)
- Strukturiertes Logging in `pipeline.log` pro Capture
- TOML-Config funktioniert, Defaults sinnvoll

### Phase 2 — Watch-Folder-Daemon

- `autosplat watch <folder>` läuft als langlebiger Prozess
- Queue-basiert (sequentielle Verarbeitung, kein paralleles Training auf M5)
- Detection: nur abgeschlossene Files verarbeiten (Größen-Stabilität prüfen, nicht direkt bei `created`)
- Auto-Recovery nach Crash (Status persistent in `~/.autosplat/state.json`)

### Phase 3 — Quality-Validation & Retry

- Pre-flight checks: Video-Länge, Auflösung, FPS plausibel?
- Per-Stage-Validation: hat COLMAP genug Cameras registriert? (Threshold konfigurierbar)
- Adaptive Retry mit veränderten Parametern bei Fehlschlag
- Skipped-Frames-Detection in FFmpeg

### Phase 4 — Obsidian-Integration

- Auto-erstellte Capture-Notiz in `<vault>/PARA/Projects/3D-Captures/`
- Frontmatter mit: Capture-Datum, Source-Video, Frame-Count, COLMAP-Stats, Training-Dauer, Output-Path
- Embed-Link auf `.ply`-File (via Obsidian-Attachment-Folder)
- Auslöser via `[[Capture-MOC]]` Update

-----

## 6. Konfigurations-Spec

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
attach_ply = false             # PLY-Files sind groß, default off

[logging]
level = "INFO"
console = "rich"               # rich | plain
log_to_file = true
```

User-Override via `~/.config/autosplat/config.toml` (XDG-Style) oder `--config <path>`.

-----

## 7. CLI-Interface-Spec

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

Exit-Codes: `0` success, `1` user error, `2` pipeline failure, `3` dep missing.

-----

## 8. Dependencies & Setup

### 8.1 System-Dependencies (Homebrew)

```bash
brew install ffmpeg colmap python@3.11 uv
```

### 8.2 Brush-Binary

Nicht in Homebrew. Fetch-Script lädt das passende Release-Binary von GitHub (`ArthurBrussee/brush`), legt es nach `~/AutoSplat/bin/brush`, macht es executable, und versioniert es in `~/AutoSplat/bin/.brush-version`.

### 8.3 Python-Setup (via uv)

```bash
uv sync                # installs from pyproject.toml + uv.lock
uv run autosplat doctor
```

### 8.4 Python-Dependencies (pyproject.toml)

```
typer>=0.12
pydantic>=2.7
watchdog>=4.0
structlog>=24.1
rich>=13.7
tomli-w>=1.0   # only for python <3.11
opencv-python>=4.9  # for blur detection
```

Optional (für Phase 4): `python-frontmatter` für Obsidian-Note-Generierung.

-----

## 9. Error-Handling & Logging

### 9.1 Logging-Konvention

Jeder Capture bekommt eine `pipeline.log` mit strukturierten JSON-Events:

```json
{"ts": "2026-05-14T12:00:00Z", "stage": "preprocess", "event": "frames_extracted", "count": 247, "duration_s": 12.3}
```

Console-Output via Rich für Live-Progress, JSON für Audit-Trail.

### 9.2 Failure-Modes & Recovery

|Stage     |Häufige Failure-Modes                        |Recovery                                   |
|----------|---------------------------------------------|-------------------------------------------|
|Preprocess|Korruptes Video, kein Audio-Track ignorierbar|Skip file, log warning                     |
|SfM       |Zu wenig Features (z.B. wenig Textur)        |Retry mit anderen COLMAP-Params; sonst skip|
|SfM       |<60% Cameras registriert                     |Retry mit `exhaustive` matcher             |
|Training  |Brush-Binary missing/incompatible            |Halt, doctor-Hinweis                       |
|Training  |OOM (RAM)                                    |Retry mit `resolution_cap` halbiert        |
|Export    |PLY-File <1MB                                |Treat as failure, no auto-open             |

### 9.3 State-Persistenz

`~/.autosplat/state.json`:

```json
{
  "queue": ["path/to/video2.mp4"],
  "in_progress": {"path": "video1.mp4", "stage": "training", "started": "..."},
  "completed": [...]
}
```

-----

## 10. Testing-Strategie

### 10.1 Unit-Tests (schnell)

- Config-Parsing & Validierung
- FFmpeg-Command-Builder (string assertions, no actual ffmpeg)
- Blur-Threshold-Logik mit synthetischen Bildern
- Watcher-Logik mit Fake-Filesystem-Events

### 10.2 Integration-Tests (mittel)

- Echter FFmpeg-Aufruf auf 3s-Fixture-Video
- COLMAP auf 20-Frame-Subset (mocked oder cached database)

### 10.3 E2E-Test (langsam, `@pytest.mark.slow`)

- Kompletter Run auf `tests/fixtures/tiny_video.mp4`
- Acceptance: PLY-File >100KB, COLMAP registriert >50% Frames

### 10.4 CI-Hinweis

Phase 1 läuft lokal. CI auf GitHub Actions schwierig wegen COLMAP/Brush-Setup. Nicht-Ziel für Phase 1.

-----

## 11. Akzeptanzkriterien pro Phase

### 11.1 Phase 1 (CLI-MVP)

- [ ] `autosplat doctor` erkennt fehlende Deps korrekt
- [ ] `autosplat process tests/fixtures/tiny_video.mp4` produziert valides `scene.ply`
- [ ] Pipeline-Log enthält pro Stage Start/End-Event mit Duration
- [ ] Config-Overrides via CLI funktionieren
- [ ] SuperSplat öffnet sich nach erfolgreichem Run mit geladenem Splat
- [ ] Unit-Tests grün, E2E grün

### 11.2 Phase 2 (Watcher)

- [ ] `autosplat watch ~/inbox` verarbeitet Files in Drop-Reihenfolge
- [ ] Process überlebt einzelne Capture-Failures (kein Hard-Crash)
- [ ] State-File konsistent nach Kill/Restart
- [ ] Zwei Files nacheinander in Inbox werden korrekt seriell abgearbeitet

### 11.3 Phase 3 (Quality)

- [ ] Bei schlechtem Footage (Test-Fixture: shaky_dark.mp4) → graceful retry → skip
- [ ] Validation-Failures landen mit Begründung in State-File

### 11.4 Phase 4 (Obsidian)

- [ ] Capture-Note wird im konfigurierten Vault-Pfad erstellt
- [ ] Frontmatter validiert gegen Obsidian-Bases-kompatibles Schema (s. §13)

-----

## 12. Offene Entscheidungen (vor CC-Start klären)

1. **Brush-Versionierung**: Pinning auf konkrete Release-Tag oder immer latest? → **Empfehlung:** Pin auf bekannt-gute Version in `.brush-version`-File.
2. **Capture-Naming**: Auto-Slug aus Video-Filename oder Timestamp-basiert? → **Empfehlung:** `{date}_{stem}` (z.B. `2026-05-14_neo2_garden`).
3. **Concurrent Processing**: Wirklich rein seriell auf M5? → **Empfehlung:** Ja für Phase 1-2. CPU-bound COLMAP + GPU-bound Brush würden parallel laufen können, aber Komplexität rechtfertigt das nicht im MVP.
4. **Obsidian-Vault-Pfad**: Welcher konkret? → Joe gibt vor CC-Start an, sonst Phase 4 deferred.
5. **Telemetry / Crash-Reports**: Lokal-only oder optional aggregiert? → **Empfehlung:** Lokal-only, kein Ping nach außen.

-----

## 13. Anhang A — Obsidian-Capture-Note-Template (Phase 4)

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

Kompatibel mit Obsidian-Bases (folder-scoped Base auf `type:capture` filterbar).

-----

## 14. Anhang B — Empfohlene CC-Working-Sequenz

1. CC liest dieses Dokument vollständig
2. CC erstellt Repo-Skeleton (§4) und committet als initial commit
3. CC implementiert in Reihenfolge: `config.py` → `logging.py` → `doctor.py` → `preprocess.py` → `sfm.py` → `train.py` → `export.py` → `viewer.py` → `cli.py`
4. Pro Modul: implement → unit tests → commit
5. E2E-Test als letzter Schritt von Phase 1
6. Status-Report an Architect (Cowork) mit: was funktioniert, welche Akzeptanzkriterien erfüllt, welche offen, welche Open-Decisions aus §12 noch blockieren
7. Stop after Phase 1. Phase 2-4 in separaten Sessions.

-----

## 15. Out-of-Scope / Future Work (post-MVP)

- Mesh-Reconstruction aus Splats (z.B. via SuGaR)
- Multi-Video-Fusion zu einer Szene
- Web-UI statt CLI
- iCloud-Sync-Integration für Drone-Footage
- msplat als Performance-Backend (statt Brush) für M-Serie
- Auto-Tagging via Vision-Model (was zeigt der Capture?)