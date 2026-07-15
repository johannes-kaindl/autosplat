# Share-Bundle-Migration auf `embed/` + DMG-Packaging-Fix — Design

**Datum:** 2026-07-15 · **Status:** approved · **Scope:** `pipeline/src/autosplat/webui/share*.py`, `pipeline/src/autosplat/config.py`, `pipeline/config/default.toml`, `pipeline/packaging/AutoSplat.spec`

## Ziel

Der WebUI-Share-Bundle-Export (`ShareJobRunner`) nutzt aktuell den geparkten
`viewer/` als Bundle-Runtime — CDN-abhängig (PlayCanvas von jsDelivr) und im
gepackten DMG-App **funktional kaputt** (siehe Fehleranalyse unten). Diese
Arbeit stellt die Bundle-Runtime auf `embed/` um (zero-external, siehe
`pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`) und
behebt dabei den zugrunde liegenden Pfad-Bug, der die Funktion bislang im
Frozen-App-Kontext (und potenziell auch im Dev-Checkout bei abweichendem CWD)
unbrauchbar machte.

Dies ist der in der Basis-Spec bereits vorgemerkte Folge-Slice
("Share-Bundle-Umstellung der Pipeline auf `embed/` als Bundle-Runtime —
Folge-Slice; macht Bundles dann echt zero-external").

## Fehleranalyse (Ist-Zustand, verifiziert)

- `ShareConfig.viewer_src_path` (`config.py:393-397`) hat einen **statischen**
  Default `Path("../viewer")`, aufgelöst relativ zum **Arbeitsverzeichnis**
  (`share_runner.py:98-100`, `_resolve_viewer_src`).
- Anders als die beiden Nachbar-Pfade `_packaged_default_config()`
  (`config.py:25-34`) und `_webui_dir()` (`webui/app.py:26-30`) hat dieser
  Pfad **keinen** `sys.frozen`/`sys._MEIPASS`-Fallback.
- `AutoSplat.spec`s `datas`-Liste (Zeilen 33-39) bündelt `viewer/` nicht.
- Empirisch bestätigt: im gebauten `AutoSplat.app` existiert nirgends eine
  `viewer.html`. Ein Klick auf „Create share bundle" in der gepackten App
  scheitert mit `FileNotFoundError: viewer sources not found at …`
  (abgefangen in `share_runner.py:93-96`, als fehlgeschlagener Job sichtbar,
  kein Crash).
- Der DMG-Design-Spec (`2026-05-29-dmg-app-design.md`) ist ~6,5 Wochen älter
  als das Share-Bundle-Feature (v1.13.0, 2026-07-14) und hat es nie
  berücksichtigt.

## Entscheidungen (mit dem Maintainer geklärt)

| Frage | Entscheidung |
|---|---|
| Bundle-Runtime | **`embed/`** statt `viewer/` — macht Bundles zero-external |
| Config-Feld | **Umbenennen** `viewer_src_path` → `embed_src_path` (kein stiller Alias — der alte Name würde für immer in die Irre führen) |
| Pfad-Auflösung | **`default_factory`** statt statischem `Path("../viewer")`-Default — frozen-aware nach dem Muster von `_packaged_default_config()`, behebt den CWD-Bug an der Wurzel (nicht nur den Frozen-Fall) |
| `default.toml` | Die explizite `viewer_src_path = "../viewer"`-Zeile wird **entfernt**, nicht umbenannt — sonst überschreibt sie den neuen smarten Python-Default wieder |
| Redirect-Datei | **Entfällt** — `embed/index.html` ist selbst der Entry-Point (`?src=…`), anders als `viewer.html`. Wird 1:1 als Bundle-Root-`index.html` kopiert |
| DMG neu bauen/signieren/releasen | **Nicht Teil dieser Arbeit** — eigener, expliziter Schritt nach Rücksprache (Codesigning/Notary-Credentials, öffentlich sichtbares Artefakt) |

## Code-Änderungen

### `pipeline/src/autosplat/config.py`

Neue Funktion `_default_embed_src()` direkt neben `_packaged_default_config()`,
gleiches Muster:

```python
def _default_embed_src() -> Path:
    """Locate the embed/ viewer sources copied into share bundles — frozen-aware.

    In a PyInstaller bundle, resolve against `sys._MEIPASS` (where build_app.sh
    stages `embed/`); otherwise use the monorepo-relative path (config.py →
    autosplat → src → pipeline → repo root → embed).
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "embed"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[3] / "embed"
```

`ShareConfig.viewer_src_path` → `embed_src_path`, mit `default_factory` statt
`default`:

```python
embed_src_path: Path = Field(
    default_factory=_default_embed_src,
    description="Path to the embed/ viewer sources copied into each share "
    "bundle. Frozen-app aware (resolves inside the DMG bundle when packaged); "
    "override only if your embed/ checkout lives elsewhere.",
)
```

### `pipeline/config/default.toml`

`[share]`-Sektion: `viewer_src_path = "../viewer"`-Zeile **entfernen**,
Kommentar anpassen (kein `embed_src_path`-Eintrag — der Python-Default trägt).

### `pipeline/src/autosplat/webui/share.py`

- Modul-Docstring: „viewer runtime" → „embed viewer runtime", Redirect-Erwähnung
  raus.
- `_VIEWER_ALLOWLIST` → `_EMBED_ALLOWLIST = ("index.html", "js", "css", "vendor")`.
- `_INDEX_REDIRECT`-Konstante **entfällt** komplett.
- `assemble_bundle(sog_path, embed_src, share_dir, token)` (Parametername
  `viewer_src` → `embed_src`):
  - Existenz-Check: `(embed_src / "index.html").exists()` statt
    `viewer_src / "viewer.html"`.
  - Kopiert `_EMBED_ALLOWLIST`-Einträge (inkl. `index.html` selbst — landet
    direkt als Bundle-Root-`index.html`, **keine** separate Redirect-Datei mehr
    geschrieben).
  - `c/scene.sog`-Logik unverändert.
- `share_link(base_url, token)`: hängt `?src=c/scene.sog` an den
  zurückgegebenen Link an, da `index.html` jetzt der direkte Embed-Entry-Point
  ist (vorher übernahm das die Redirect-Datei):
  ```python
  return f"{base_url.rstrip('/')}/{token}/?src=c/scene.sog"
  ```

### `pipeline/src/autosplat/webui/share_runner.py`

- `_resolve_viewer_src` → `_resolve_embed_src`, liest
  `self._cfg.share.embed_src_path` statt `viewer_src_path`. Logik unverändert
  (`p if p.is_absolute() else (Path.cwd() / p)`) — greift jetzt nur noch für
  einen expliziten *relativen* User-Override; der Default ist bereits absolut
  (aus `_default_embed_src()`), CWD spielt für den Normalfall keine Rolle mehr.
- Variable/Parameter-Umbenennungen `viewer_src` → `embed_src` in `_run()`.

### `pipeline/packaging/AutoSplat.spec`

Neue `datas`-Einträge (Allowlist-Prinzip, **nicht** der ganze Ordner — `tests/`
und `AGENTS.md` bleiben draußen):

```python
datas = [
    (_p("src/autosplat/webui/templates"), "autosplat/webui/templates"),
    (_p("src/autosplat/webui/static"), "autosplat/webui/static"),
    (_p("config/default.toml"), "config"),
    (_p("scripts/install_deps.sh"), "scripts"),
    (_p("scripts/fetch_brush.sh"), "scripts"),
    (_p("..", "embed", "index.html"), "embed"),
    (_p("..", "embed", "css"), "embed/css"),
    (_p("..", "embed", "js"), "embed/js"),
    (_p("..", "embed", "vendor"), "embed/vendor"),
]
```

Kommentar über `datas` um den `embed/`-Zweck ergänzen (Analogie zu
`config.py`s `sys._MEIPASS`-Auflösung).

## Tests (anzupassen)

Vier bestehende Testdateien referenzieren die alte Viewer-Allowlist:

- `pipeline/tests/webui/test_share.py`: `_fake_viewer()` → `_fake_embed()`,
  erzeugt `index.html` statt `viewer.html`, `vendor/` statt `assets/demo/` als
  Struktur; Assertions auf `index.html` (Entry-Point, kein Redirect-Inhalt mehr
  — stattdessen prüfen, dass die Datei den Original-Embed-Inhalt trägt),
  `c/scene.sog`, Allowlist-Ausschlüsse (`tests/` weiterhin nicht kopiert).
- `pipeline/tests/webui/test_share_runner.py`: `_fake_viewer()` → analog,
  `cfg.share.viewer_src_path` → `cfg.share.embed_src_path`, `job.link`-Assertion
  um `?src=c/scene.sog`-Suffix ergänzen.
- `pipeline/tests/webui/test_share_routes.py`: gleiche Umbenennung.
- `pipeline/tests/test_config.py`: Assertion auf den alten String-Default
  (`"../viewer"`) ersetzen durch eine Prüfung, dass `cfg.share.embed_src_path`
  ein absoluter Pfad ist, der auf ein `embed`-Verzeichnis zeigt (z. B.
  `.name == "embed"` und `.is_absolute()`), statt eines exakten String-Vergleichs
  (der Pfad ist jetzt maschinenabhängig absolut, nicht mehr der literale String
  `"../viewer"`).

`cd pipeline && uv run pytest -q` muss vor jedem Commit grün sein.

## Doku-Updates

- `pipeline/CHANGELOG.md`: neuer `[Unreleased]`-Eintrag — Share-Bundles sind
  jetzt zero-external (embed/-Runtime statt CDN-viewer), Fix für den DMG-Bug.
- `pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`: den
  "Bewusst außerhalb des Scopes"-Punkt zur Share-Bundle-Umstellung als erledigt
  markieren (Verweis auf diese Spec), nicht löschen (Historie).

## Manueller Smoke (nach Implementierung)

1. `cd pipeline && uv run autosplat webui` (Dev-Checkout, absoluter
   `embed_src_path`-Default greift unabhängig vom Start-CWD).
2. Eine bestehende Capture öffnen → „Create share bundle" klicken.
3. Bundle-Ordner (`<capture>/share/<token>/`) prüfen: `index.html`, `js/`,
   `css/`, `vendor/`, `c/scene.sog` vorhanden; **kein** `viewer.html`, **kein**
   `tests/`.
4. Bundle lokal servieren (`python3 -m http.server` im Bundle-Ordner) und im
   Browser öffnen — Szene lädt zero-external (Netzwerk-Tab: nur
   `localhost`-Requests).
5. Zurückgegebener Share-Link (`job.link` in der UI) enthält
   `?src=c/scene.sog` und lädt beim Öffnen direkt die Szene (Gate sichtbar,
   Klick lädt).

## Bewusst außerhalb des Scopes

- **DMG neu bauen, signieren, notarisieren, als Release hochladen** — eigener
  Schritt nach explizitem Go, nicht Teil dieser Code-Änderung. Der
  `AutoSplat.spec`-Fix macht einen *zukünftigen* Build korrekt; das aktuell
  gebaute `AutoSplat.dmg` bleibt bis zum nächsten Rebuild auf dem alten,
  kaputten Stand.
- Poster/Autoplay-Parameter in Share-Bundle-Links (nicht angefragt, YAGNI).
- Migration bereits existierender, älterer Share-Bundles (die liegen bereits
  als fertige Ordner/Zips vor und werden von dieser Änderung nicht
  rückwirkend angefasst).
