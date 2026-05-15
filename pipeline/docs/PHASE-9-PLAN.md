# PHASE-9-PLAN — Local SuperSplat Auto-Open (Option A)

*Plan-Bau-Burst 2026-05-14 · Status: **Decision-Gate** · Autor: CC-Executor*
*Basis: `docs/PHASE-9-RECON.md`, commit `889c333`*

---

## § 1 — Kontext + Bezug zur Recon

Der load-bearing Befund aus der Recon: `viewer.py` hat seit Phase 1 einen stillen Fehler — es baut URLs der Form `https://playcanvas.com/supersplat/editor?load=http://127.0.0.1:8765/scene.ply`, die wegen Mixed-Content-Blockierung (HTTPS-Seite kann HTTP-Resource auf localhost nicht fetchen) im Browser nie funktioniert haben. PLY wurde daher immer manuell per Drag-and-drop geladen. Zusätzlich startet kein HTTP-Server für die PLY-Datei — `open_in_viewer` baut nur die URL und öffnet den Browser, ohne die Datei je zu servieren.

Option A löst beide Probleme mit einer lokal gebauten SuperSplat-Instanz (`http://localhost:3000`): gleiches Schema + Host wie der PLY-Server → kein CORS/Mixed-Content. SuperSplat ist MIT, baut sauber mit Node.js+Rollup, unterstützt `?load=URL` nativ.

**Explicit Out of Scope für Phase 9:** Cloud-Share-URL-Automation (`embed_view_url` bleibt manuell), Capture-Browser-UI, Mobile-Support, Full WebUI, iframe-Fallback-Templating, Preview-Screenshot-Generierung.

---

## § 2 — Sub-Phasen-Architektur

### Sub-Phase 9.1 — Config-Erweiterung + URL-Builder-Fix
*~0.5 Tag — keine externen Abhängigkeiten, reine Python-Änderungen*

**Scope:** Neues `target`-Value `"supersplat-local"`, neue Config-Felder, korrekter URL-Builder.

**Commits:**
1. `feat(phase-9.1): ViewerConfig — supersplat-local target + supersplat_local_port + dist_path`
2. `feat(phase-9.1): viewer.py — URL-builder für supersplat-local; localhost statt 127.0.0.1`
3. `test(phase-9.1): viewer URL-builder-Tests (supersplat-local, remote, playcanvas)`

**Tags:** `autosplat-pre-phase-9.1-config-url` → `autosplat-post-phase-9.1-config-url`

**Konkrete Code-Änderungen:**

`config.py` → `ViewerConfig`:
```python
# Neue Felder:
supersplat_local_port: int = Field(default=3000, ge=1024, le=65535,
    description="Port for locally-built SuperSplat dev server.")
supersplat_dist_path: Path = Field(default=Path("target/supersplat/dist"),
    description="Path to built SuperSplat dist/ directory.")
# target erweitern:
target: Literal["supersplat", "supersplat-local", "playcanvas", "none"]
```

`config/default.toml` → `[viewer]`:
```toml
supersplat_local_port = 3000
supersplat_dist_path = "target/supersplat/dist"
```

`viewer.py` → `_build_viewer_url`:
- `"supersplat-local"` → `f"http://localhost:{supersplat_port}?load=http://localhost:{ply_port}/{ply_name}"`
- `"supersplat"` → weiterhin Remote-URL (für Nutzer ohne lokales Build)
- `serve_directory` Binding: `"127.0.0.1"` bleibt für Security; URL zum Browser: `localhost` statt `127.0.0.1`

`viewer.py` → `open_in_viewer` für `supersplat-local`:
- Kein `webbrowser.open()` inline (kein Server läuft nach Pipeline-Exit)
- Loggt `INFO viewer.local_hint`: `"Run: autosplat serve <output_dir> --with-supersplat"`

**DoD 9.1:**
- [ ] `target = "supersplat-local"` ist valider Pydantic-Wert, Config lädt ohne Fehler
- [ ] `_build_viewer_url("supersplat-local", "scene.ply", ply_port=8765, ss_port=3000)` → `"http://localhost:3000?load=http://localhost:8765/scene.ply"`
- [ ] `open_in_viewer` für `supersplat-local` öffnet keinen Browser, loggt hint
- [ ] Alle Tests grün (≥ 122 gesamt)

**Test-Adds 9.1: ~6**
- URL-builder: supersplat-local, supersplat-remote, playcanvas, none
- `open_in_viewer` mit `target="supersplat-local"` → kein `webbrowser.open`, hint geloggt
- Config-Roundtrip: `supersplat_local_port` + `supersplat_dist_path` aus TOML

---

### Sub-Phase 9.2 — SuperSplat Setup-Script + Doctor
*~0.5 Tag — erfordert Node.js/npm auf dem System*

**Scope:** Reproduzierbares Build-Script, Doctor-Check für lokales SuperSplat-Dist.

**Commits:**
1. `feat(phase-9.2): scripts/setup_supersplat.sh — clone, npm ci, npm run build, verify`
2. `feat(phase-9.2): doctor — supersplat-dist check (required=False, WARN wenn fehlt)`
3. `test(phase-9.2): doctor supersplat-check — OK + WARN + target≠supersplat-local → skip`

**Tags:** `autosplat-pre-phase-9.2-setup-doctor` → `autosplat-post-phase-9.2-setup-doctor`

**`scripts/setup_supersplat.sh` — Design:**
```bash
#!/usr/bin/env bash
set -euo pipefail

SUPERSPLAT_REPO="https://github.com/playcanvas/supersplat"
SUPERSPLAT_PIN="main"          # nach erstem Erfolg auf konkret-guten commit pinnen
DEST="${REPO_ROOT}/target/supersplat"

# Precondition: node + npm
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found. Install: brew install node"; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm not found";  exit 1; }

# Clone oder update
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" fetch --quiet && git -C "$DEST" checkout "$SUPERSPLAT_PIN"
else
  git clone --depth 1 --branch "$SUPERSPLAT_PIN" "$SUPERSPLAT_REPO" "$DEST"
fi

cd "$DEST"
npm ci --prefer-offline --loglevel=warn
npm run build

# Verify
[ -f "$DEST/dist/index.html" ] || { echo "ERROR: dist/index.html missing after build"; exit 1; }
echo "SuperSplat built → $DEST/dist/"
```

**Doctor-Integration:**
```python
def _check_supersplat(config: Config) -> CheckResult | None:
    if config.viewer.target != "supersplat-local":
        return None   # Skip — not relevant for remote-only setup
    dist_index = config.viewer.supersplat_dist_path / "index.html"
    if dist_index.exists():
        return CheckResult(name="supersplat", ok=True,
            detail=f"dist at {dist_index.parent}", required=False)
    return CheckResult(name="supersplat", ok=False, required=False,
        detail=f"dist missing at {dist_index.parent} — run scripts/setup_supersplat.sh")
```
→ `run_doctor()` ruft `_check_supersplat` auf, filtert `None` raus.

**DoD 9.2:**
- [ ] `bash scripts/setup_supersplat.sh` läuft durch, `target/supersplat/dist/index.html` existiert
- [ ] `autosplat doctor` zeigt `supersplat WARN` wenn dist fehlt (nur wenn target=supersplat-local)
- [ ] `autosplat doctor` zeigt `supersplat OK` nach Setup
- [ ] Alle Tests grün (≥ 125 gesamt)

**Gate-1 (manuell, vor 9.3):**
> Jay führt aus: `bash scripts/setup_supersplat.sh`
> Danach: `python -m http.server 3000 --directory target/supersplat/dist &` und `open http://localhost:3000`
> Erwartung: SuperSplat öffnet sich im Browser, zeigt die UI (kein Splat geladen — Drag-and-drop noch nötig).
> Gate ist bestanden wenn SuperSplat lädt. STOP wenn Build-Error oder leere Seite → Befund an Cowork.

**Test-Adds 9.2: ~3**
- Doctor-Check: dist vorhanden → OK
- Doctor-Check: dist fehlt + target=supersplat-local → WARN
- Doctor-Check: target=supersplat (remote) → kein supersplat-Check in output

---

### Sub-Phase 9.3 — `autosplat serve` CLI-Command
*~1 Tag — Prozess-Management, graceful shutdown, subprocess-Kontrolle*

**Scope:** Neuer CLI-Command der PLY-Server + SuperSplat-Server startet, Browser öffnet, blockiert bis Ctrl+C.

**Commits:**
1. `feat(phase-9.3): viewer.py — serve_supersplat_local context manager`
2. `feat(phase-9.3): cli.py — serve command mit --with-supersplat, --ply-port, --no-open-browser`
3. `test(phase-9.3): serve-command lifecycle — beide Server starten, shutdown auf signal`

**Tags:** `autosplat-pre-phase-9.3-serve-cmd` → `autosplat-post-phase-9.3-serve-cmd`

**`viewer.py` — neuer Context-Manager:**
```python
@contextmanager
def serve_supersplat_local(
    supersplat_dist: Path,
    supersplat_port: int,
    ply_dir: Path,
    ply_port: int,
) -> Iterator[dict[str, str]]:
    """Start both servers. Yields dict with supersplat_url + ply_url."""
    with serve_directory(supersplat_dist, supersplat_port) as ss_base:
        with serve_directory(ply_dir, ply_port) as ply_base:
            yield {"supersplat": ss_base, "ply": ply_base}
```

**`cli.py` — neuer Command:**
```python
@app.command()
def serve(
    capture_dir: Path = typer.Argument(..., help="Directory containing scene.ply."),
    with_supersplat: bool = typer.Option(False, "--with-supersplat"),
    ply_port: int | None = typer.Option(None, "--ply-port"),
    supersplat_port: int | None = typer.Option(None, "--supersplat-port"),
    no_open_browser: bool = typer.Option(False, "--no-open-browser"),
    config: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    cfg = _load_or_die(config)
    ply_file = _find_ply(capture_dir)     # sucht scene.ply in capture_dir oder capture_dir/output/
    effective_ply_port = ply_port or cfg.viewer.local_http_port
    effective_ss_port  = supersplat_port or cfg.viewer.supersplat_local_port
    ...
    # Blockiert bis Ctrl+C (signal.pause() oder threading.Event.wait())
```

**`_find_ply(capture_dir)` Logik:**
1. `capture_dir/scene.ply` → direkt
2. `capture_dir/output/scene.ply` → in outputs-Subdir
3. Erstes `*.ply` in `capture_dir` → Fallback
4. Kein PLY → Exit mit Fehlermeldung

**Graceful Shutdown:**
```python
import signal
stop_event = threading.Event()
signal.signal(signal.SIGINT,  lambda *_: stop_event.set())
signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
# ...
with serve_supersplat_local(...) as urls:
    if not no_open_browser:
        ply_name = ply_file.name
        browser_url = f"{urls['supersplat']}?load={urls['ply']}/{ply_name}"
        webbrowser.open(browser_url)
    print(f"Serving. Press Ctrl+C to stop.")
    stop_event.wait()   # blocks here
```

**Portkonflikt (STOP-Trigger):**
`socketserver.ThreadingTCPServer` wirft `OSError: [Errno 48] Address already in use` → exception propagiert als Exit-Code `EXIT_USER_ERROR` mit Meldung `"Port {port} already in use — use --ply-port / --supersplat-port to override"`.

**DoD 9.3:**
- [ ] `autosplat serve /path/to/capture --with-supersplat` → Browser öffnet, PLY lädt automatisch (keine Drag-and-drop)
- [ ] Ctrl+C → beide Server shutdown, Prozess beendet sich sauber
- [ ] Port-Konflikt → klare Fehlermeldung, Exit 1
- [ ] Smoke: manueller Test durch Jay mit burgstall-PLY
- [ ] Alle Tests grün (≥ 131 gesamt)

**Test-Adds 9.3: ~6**
- `serve_supersplat_local`: beide Server starten, correkter yield, shutdown
- `_find_ply`: direkter Pfad / output-Subdir / fallback / kein PLY
- `serve` CLI: Port-Konflikt-Exit, `--no-open-browser` unterdrückt `webbrowser.open`

---

### Sub-Phase 9.4 — embed_url Auto-Fill nach Pipeline-Run
*~0.5 Tag — pipeline.py + obsidian.py, keine neuen Module*

**Scope:** Nach erfolgreichem Training + Export: `embed_url` mit localhost-URL automatisch in die Obsidian-Note schreiben.

**Commits:**
1. `feat(phase-9.4): pipeline.py — build embed_url für supersplat-local target`
2. `test(phase-9.4): embed_url Auto-Fill — supersplat-local target, user-override preserved, remote target → None`

**Tags:** `autosplat-pre-phase-9.4-embed-url` → `autosplat-post-phase-9.4-embed-url`

**`pipeline.py` — Änderung in `run_pipeline`:**
```python
# Nach export_capture, vor obsidian.write_capture_note:
embed_url: str | None = None
if (
    config.obsidian.enabled
    and config.viewer.target == "supersplat-local"
):
    ply_name = exp.output_ply.name   # "scene.ply"
    embed_url = (
        f"http://localhost:{config.viewer.supersplat_local_port}"
        f"?load=http://localhost:{config.viewer.local_http_port}/{ply_name}"
    )

note_data = obsidian_mod.CaptureNoteData(
    ...
    embed_url=embed_url,   # War bisher implizit None
    ...
)
```

**Merge-Policy (bereits korrekt in Phase 8):**
`embed_url` ist in `_COWORK_GENERATED_BUT_USER_OVERRIDABLE` → wenn User eine superspl.at-URL manuell eingetragen hat, wird sie auf Re-Run bewahrt. Kein weiterer Code nötig.

**Beispiel-Result in Obsidian-Note:**
```yaml
embed_url: "http://localhost:3000?load=http://localhost:8765/scene.ply"
```

**Gate-2 (manuell, nach 9.4):**
> Jay führt `autosplat process <video>` aus, öffnet generierte Note.
> Erwartet: `embed_url` ist gesetzt (nicht leer), Auto-Block zeigt `<iframe src="http://localhost:3000?load=...">`.
> Mit laufendem `autosplat serve <capture_dir> --with-supersplat`: iframe rendert Splat in Obsidian Reading-Mode.
> STOP wenn embed_url leer bleibt → Befund an Cowork.

**DoD 9.4:**
- [ ] `embed_url` ist nach Pipeline-Run automatisch gesetzt (nicht `""`)
- [ ] Re-Run bei bestehender Note mit user-eingetragener superspl.at-URL: URL bleibt erhalten
- [ ] `target = "supersplat"` (remote) → `embed_url = None` (kein lokaler Pfad)
- [ ] Alle Tests grün (≥ 135 gesamt)

**Test-Adds 9.4: ~4**
- `embed_url` korrekt gebaut für supersplat-local target
- `embed_url = None` wenn target=supersplat (remote)
- Merge-Policy: user-override-URL bleibt beim Re-Run erhalten
- Pipeline-Integration: embed_url fließt in `CaptureNoteData`

---

### Sub-Phase 9.5 — macOS Notification nach Trainingsende
*~0.5 Tag — neues Modul, opt-in, isolated*

**Scope:** Nach erfolgreichem Brush-Training: macOS Notification Center Meldung.

**Commits:**
1. `feat(phase-9.5): notification.py — osascript notify_training_complete, graceful no-op`
2. `feat(phase-9.5): config.py + default.toml — notify_on_complete (default false)`
3. `feat(phase-9.5): pipeline.py — call notify nach train stage`
4. `test(phase-9.5): notify — mock subprocess, non-macOS no-op, graceful failure`

**Tags:** `autosplat-pre-phase-9.5-notification` → `autosplat-post-phase-9.5-notification`

**`src/autosplat/notification.py`:**
```python
import platform, subprocess
from .logging import get_logger
logger = get_logger(__name__)

def notify_training_complete(
    capture_name: str, duration_s: float, gaussians: int
) -> None:
    if platform.system() != "Darwin":
        return
    mins = int(duration_s // 60)
    secs = int(duration_s % 60)
    duration_str = f"{mins}m {secs}s" if mins else f"{secs}s"
    msg = f"{capture_name} — {gaussians:,} Gaussians in {duration_str}"
    title = "autosplat: Training complete"
    script = f'display notification "{msg}" with title "{title}"'
    try:
        subprocess.run(["osascript", "-e", script],
                       capture_output=True, timeout=5, check=False)
    except Exception as exc:
        logger.debug("notification.failed", error=str(exc))
```

**`config.py` — `ViewerConfig` Erweiterung (oder neuer `[notifications]` Block):**
```toml
[viewer]
notify_on_complete = false   # macOS Notification nach Training. Opt-in.
```

**`pipeline.py` — Placement:**
```python
# Nach train_mod.run_brush(...), VOR export:
if getattr(config.viewer, "notify_on_complete", False):
    from . import notification as notif_mod
    notif_mod.notify_training_complete(
        capture_name=_make_capture_name(video_path),
        duration_s=training_duration,
        gaussians=0,   # noch nicht bekannt — PLY nicht geparst; oder weglassen bis nach export
    )
```

*Note: Gaussians-Count kommt aus PLY-Header (Phase 4 `read_ply_header`), der erst nach Export bekannt ist. Für Phase 9 Notification: entweder aus `train.py`-Progressparser schätzen oder 0/None lassen und Meldung ohne Gaussians zeigen. Die Notification-Platzierung NACH Training ist das Kern-Goal.*

**DoD 9.5:**
- [ ] `notify_on_complete = true` in Config → macOS Notification erscheint nach Trainingsende
- [ ] Default `false` → keine Notification
- [ ] Non-macOS → silent no-op
- [ ] `osascript`-Fehler → Debug-Log, kein Pipeline-Crash
- [ ] Alle Tests grün (≥ 139 gesamt)

**Test-Adds 9.5: ~4**
- `notify_training_complete` ruft `osascript` mit korrektem Argument
- Non-macOS (mock `platform.system()` → "Linux") → kein subprocess-Call
- `subprocess.run` wirft Exception → kein crash, debug-log
- `config.viewer.notify_on_complete = false` → Pipeline ruft notify nicht auf

---

## § 3 — Test-Strategie

| Sub-Phase | Test-Klassen | Coverage-Fokus | Smoke |
|---|---|---|---|
| 9.1 | Unit (URL-builder, Config-Parsing) | Alle target-Varianten, localhost vs. 127.0.0.1, Config-Defaults | TOML-Config laden mit neuen Feldern |
| 9.2 | Unit (doctor check) | dist vorhanden/fehlt, target-Check | `bash scripts/setup_supersplat.sh` → dist prüfen |
| 9.3 | Unit (process lifecycle, _find_ply, port-error) | Server-Start/Stop, URL-Bau, Fallback-PLY-Suche | Manuell: `autosplat serve <dir> --with-supersplat` |
| 9.4 | Unit (embed_url build, merge-policy) | supersplat-local → URL korrekt; remote → None; user-override | `autosplat process <video>` → Note-Inhalt prüfen |
| 9.5 | Unit (osascript mock, platform mock) | Happy-path, non-macOS, exception | Manuell: Notification erscheint nach Training |

**Test-Count-Schätzung:**
- 9.1: +6 Tests
- 9.2: +3 Tests
- 9.3: +6 Tests
- 9.4: +4 Tests
- 9.5: +4 Tests
- **Gesamt neu: ~23 Tests → Phase-9-Post-Total: ~139** (aktuell 116)

---

## § 4 — STOP-Triggers

| Trigger | Bedingung | Aktion |
|---|---|---|
| **Node.js/npm fehlt** | `setup_supersplat.sh` schlägt bei `command -v node` fehl | STOP. Befund melden: "Node.js nicht installiert. Optionen: (a) `brew install node`, (b) target=supersplat (remote) weiternutzen". Kein Auto-Install — externe Dep, Jay entscheidet. |
| **SuperSplat Build-Fehler** | `npm run build` schlägt fehl (Rollup-Fehler, TypeScript-Fehler) | STOP. Build-Log melden. Mögliche Ursache: SuperSplat-`main` hat Breaking Change. Fix: `SUPERSPLAT_PIN` auf letzten bekannt-guten Commit setzen. |
| **Port bereits belegt** | `:3000` oder `:8765` in Benutzung | Nicht STOP — konfigurierbarer Port via `--supersplat-port` / `--ply-port`. Klare Fehlermeldung + Hinweis auf Override-Flags. Kein Auto-Port-Scan (zu magisch). |
| **`?load=` nimmt kein URL** | Falls SuperSplat-Update den Parameter entfernt | STOP. Plan-Annahme falsifiziert. Lösung: nach lokalem Build testen, ggf. PLY per File-Input-Dialog öffnen (Post-9-Workaround dokumentieren). |
| **Gate-1 fehlägt (SuperSplat lädt nicht)** | Weiße Seite oder JS-Error nach Setup | STOP vor 9.3. Untersuche: MIME-Type für `.js`-Dateien korrekt? `http.server` vs. dev-server? Ggf. `npm run serve` statt statisches Serving. |
| **Gate-2 schlägt fehl (embed_url leer)** | Note zeigt `embed_url: ""` nach Pipeline-Run | STOP vor 9.5. Pipeline-Log prüfen ob `obsidian.enabled=true` und `target=supersplat-local`. |

---

## § 5 — Rollback-Pfad

**Tag-Convention (annotated, lokal-only):**

```
autosplat-pre-phase-9-recon         ← gesetzt, HEAD: 29f81f3
autosplat-post-phase-9-recon        ← gesetzt, HEAD: 889c333
autosplat-pre-phase-9-plan          ← gesetzt, HEAD: 889c333 (dieser Burst)
autosplat-post-phase-9-plan         ← wird nach Commit gesetzt

autosplat-pre-phase-9.1-config-url  ← vor Sub-Phase 9.1
autosplat-post-phase-9.1-config-url ← nach Sub-Phase 9.1

autosplat-pre-phase-9.2-setup-doctor
autosplat-post-phase-9.2-setup-doctor

autosplat-pre-phase-9.3-serve-cmd
autosplat-post-phase-9.3-serve-cmd

autosplat-pre-phase-9.4-embed-url
autosplat-post-phase-9.4-embed-url

autosplat-pre-phase-9.5-notification
autosplat-post-phase-9.5-notification
```

**Rollback-Befehl:**
```bash
git reset --hard autosplat-pre-phase-9.X-<slug>^{}
```

`^{}` dereferenziert den annotierten Tag auf den Commit. `--hard` verwirft Working-Tree-Änderungen — immer Pre-Tag zuerst prüfen.

---

## § 6 — DoD pro Sub-Phase (Gesamtübersicht)

| Sub-Phase | Unit-Tests grün | Smoke | Manuell Jay |
|---|---|---|---|
| **9.1** | ≥ 122 | `uv run autosplat config show` zeigt supersplat-local Felder | — |
| **9.2** | ≥ 125 | `bash scripts/setup_supersplat.sh` → `dist/index.html` exists | **Gate-1:** `open http://localhost:3000` → SuperSplat lädt |
| **9.3** | ≥ 131 | `uv run autosplat serve <dir> --no-open-browser` → curl :8765 + :3000 erreichbar, Ctrl+C sauber | **Smoke durch Jay:** PLY lädt automatisch, kein Drag-and-drop |
| **9.4** | ≥ 135 | `autosplat process <tiny_video>` → Note-Datei enthält `embed_url: "http://localhost..."` | **Gate-2:** Note in Obsidian öffnen, iframe sichtbar mit laufendem Server |
| **9.5** | ≥ 139 | `notify_on_complete = true` in Config + Mini-Pipeline-Lauf → Notification | Manuell: Notification erscheint nach echtem Training |

---

## § 7 — Out-of-Scope (Phase 9)

Klar abgegrenzt — **nicht implementieren**, auch wenn es "nur kurz" wirkt:

- Cloud-Share-URL-Automation (`embed_view_url` manuell befüllen bleibt Standard)
- Capture-Browser-UI (Obsidian Bases reichen)
- Mobile-Support (localhost-URLs funktionieren auf iOS/Android nicht)
- iframe-Fallback-Templating für offline/mobile (Phase 10)
- Preview-Screenshot-Generierung (Phase 10)
- `autosplat serve` ohne expliziten capture_dir (auto-latest Detection, Phase 10)
- Multi-Capture-Concurrent-View
- SuperSplat-Cleanup-Automatisierung (per Definition manuell)
- WebUI (Option B/C: verworfen bis Nutzungsvolumen steigt)

---

## § 8 — Konzeptpapier-Front-Bezug

**§5.2 Strukturelle Fragmentierung** (3 Tools → 2 Tools):
Vorher: CLI-Pipeline → *manuell Browser öffnen + navigieren* → *manuell Drag-and-drop* → SuperSplat-Editor → *manuell Cloud-Upload* → *manuell URL kopieren + in Note eintragen*.
Nach Phase 9: CLI-Pipeline → `autosplat serve <dir> --with-supersplat` → SuperSplat mit PLY auto-geladen (Cleanup bleibt manuell). `embed_url` ist automatisch in Note.
Verbleibende manuelle Schritte: SuperSplat-Cleanup + Cloud-Upload für Mobile (beides intentional manuell).

**§5.2 Tool-/Skill-Sprawl — Node.js als neue Dep:**
Trade-off bewusst: `node` + `npm` werden System-Voraussetzung für `supersplat-local` target. Gegengewicht: dauerhaft offline-fähig, kein PlayCanvas-Cloud-Account, 214 MB PLY lädt von localhost ohne Netzwerk-Transfer. ROI rational. Setup-Script macht Einmalaufwand transparent.

---

## § 9 — Decision-Gates innerhalb der Implementierung

**Gate-1 (nach Sub-Phase 9.2, vor 9.3):**

> **Checkpoint:** Jay führt manuell aus:
> ```bash
> bash scripts/setup_supersplat.sh
> python -m http.server 3000 --directory target/supersplat/dist &
> open http://localhost:3000
> ```
> **Erwartung:** SuperSplat UI lädt im Browser (leeres Canvas, keine Splat). Drag-and-drop eines kleinen PLY (bench_chill) funktioniert.
> **GO:** SuperSplat UI sichtbar → 9.3 starten.
> **STOP:** Weiße Seite, JS-Fehler, MIME-Type-Probleme → Befund an Cowork vor 9.3.

**Gate-2 (nach Sub-Phase 9.4, vor 9.5):**

> **Checkpoint:** Jay führt aus:
> ```bash
> autosplat process <video_path>   # oder autosplat process mit bereits existierendem Capture + skip-stages
> ```
> Öffnet generierte Note in Obsidian. Mit laufendem `autosplat serve <output_dir> --with-supersplat`: iframe rendert Splat.
> **GO:** Embed funktioniert, embed_url ist korrekt → 9.5 starten.
> **STOP:** iframe leer, embed_url leer oder falsch → Befund an Cowork.

---

## Anhang — Sequenz-Diagramm (Schritt-für-Schritt-Flow nach Phase 9)

```
autosplat watch ~/inbox
    └── [Video dropped]
        └── run_pipeline(video)
            ├── preprocess → sfm → quality → train
            │       └── [50+ min für burgstall]
            │           └── notify_training_complete("burgstall", 3001s) → macOS Notification
            ├── export → scene.ply @ ~/AutoSplat/outputs/burgstall/scene.ply
            └── obsidian.write_capture_note(embed_url="http://localhost:3000?load=...")
                    └── burgstall.md hat embed_url automatisch befüllt

# Getrennte Review-Session (jederzeit danach):
autosplat serve ~/AutoSplat/outputs/burgstall --with-supersplat
    ├── PLY-Server auf :8765, serving scene.ply
    ├── SuperSplat-Server auf :3000, serving target/supersplat/dist/
    └── Browser öffnet http://localhost:3000?load=http://localhost:8765/scene.ply
            └── PLY lädt automatisch — kein Drag-and-drop
                └── Cleanup (Floater, Crop) manuell
                    └── [optional] File → Publish → superspl.at-URL → manuell in embed_view_url
```
