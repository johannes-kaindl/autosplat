# Embed-Viewer — Pose-Authoring (`?pose=…&orbit=…&authoring=1`) — Design

**Datum:** 2026-07-15 · **Status:** approved · **Scope:** Erweiterung von `embed/`

## Ziel

Vor der Veröffentlichung eines Embed-Links soll sich die Kamera-Ansicht interaktiv
festlegen lassen, statt sich auf das automatische Perzentil-Framing zu verlassen.
Der Autor orbitet/zoomt frei in der Szene (Auto-Frame als Startpunkt), liest die
aktuelle Kamera-Pose per Klick als fertigen URL-Parameter aus und kopiert sie in
die Zwischenablage — bereit zum Einbetten. Die normale Embed-Seite (ohne
`authoring=1`) bleibt dabei unverändert minimal.

Kein neues UI-Panel, keine Presets, keine Speicherung — nur ein Copy-Link-Workflow
obendrauf auf die bestehende `embed/`-Komponente aus
`pipeline/docs/superpowers/specs/2026-07-14-embed-viewer-design.md`.

## Entscheidungen (mit dem Maintainer geklärt)

| Frage | Entscheidung |
|---|---|
| Was wird festgelegt | **Komplette Kamera-Pose** (Position + Fokuspunkt), nicht nur Startwinkel oder Geschwindigkeit |
| Workflow | **Interaktiv im Viewer** — kein manuelles Koordinaten-Eintippen |
| Sichtbarkeit des Capture-UI | **Eigener Autoren-Modus** (`?authoring=1`); normale Embeds bleiben unverändert |
| URL-Format der Pose | **Ein Parameter, 6 Werte** (`pose=cx,cy,cz,fx,fy,fz`) statt zweier getrennter Parameter |
| Auto-Orbit bei fixer Pose | **Eigener Parameter** (`orbit=0`/`1`), unabhängig von `pose` steuerbar — nicht an das Vorhandensein von `pose` gekoppelt |

## URL-Parameter-API (Ergänzung)

Bestehend: `src`, `poster`, `autoplay` (siehe Basis-Spec, unverändert).

| Param | Pflicht | Wirkung |
|---|---|---|
| `pose` | nein | `cx,cy,cz,fx,fy,fz` — sechs kommagetrennte Floats (Kamera-Position + Fokuspunkt). Bei gültigem Wert überspringt `loadSplat` das Perzentil-Auto-Frame und positioniert die Kamera direkt über `cc.reset(focus, camPos)`. Ungültig (falsche Arity, `NaN`) → wird ignoriert, Auto-Frame greift wie bisher |
| `orbit` | nein | `0` deaktiviert den Auto-Orbit beim Start. Default (Param fehlt oder jeder andere Wert) bleibt **an** — unverändertes heutiges Verhalten. Wirkt unabhängig davon, ob `pose` gesetzt ist |
| `authoring` | nein | `1` blendet einen zusätzlichen „Pose kopieren"-Button in den Controls ein. Ohne diesen Parameter existiert der Button nicht sichtbar für Endnutzer |

## Viewer-Runtime (`viewer.js`)

- `loadSplat(url, filename, { pose, orbit } = {})`:
  - Ist `pose` gesetzt (6 gültige Zahlen), wird `autoFrame()` **nicht** aufgerufen;
    stattdessen direkt `cc.reset(focus, camPos)` mit den übergebenen Werten.
  - Ohne `pose`: Verhalten unverändert (Auto-Frame wie bisher).
  - Nach der Positionierung: `setAutoOrbit(orbit !== false)` statt des heute fest
    verdrahteten `setAutoOrbit(true)` — der Aufrufer (main.js) reicht den
    geparsten `orbit`-Wert durch.
- Neue Funktion `getPose()` am zurückgegebenen Viewer-Objekt: liest die aktuelle
  Kamera-Position (`camera.getPosition()`) und den aktuellen Fokuspunkt
  (`cc.focusPoint` — von `vendor/camera-controls.mjs` bereits als Getter/Setter
  exponiert) und gibt `{ camPos: [x,y,z], focus: [x,y,z] }` zurück. Funktioniert
  unabhängig davon, ob die Szene per Auto-Frame oder per `pose`-Override
  positioniert wurde, und reflektiert auch nachträgliches manuelles Orbiten/Zoomen.

## Params-Parsing (`params.js`)

- `parseParams` erweitert um:
  - `pose`: `string | null` — roher Parameter-Wert, **Parsing/Validierung
    (6-Zahlen-Check) passiert separat** in einer neuen pure Funktion
    `parsePose(raw) → [number,number,number,number,number,number] | null`
    (unit-testbar, analog zu `frameBounds`).
  - `orbit`: `boolean` — `q.get('orbit') !== '0'` (Default `true`).
  - `authoring`: `boolean` — `q.get('authoring') === '1'` (gleiches Muster wie
    `autoplay`).

## Authoring-UI (`main.js` + `index.html` + `embed.css`)

- Neuer Button `#btn-copy-pose` in `#controls`, **im HTML mit `hidden`**
  ausgezeichnet. `main.js` entfernt `hidden` nur, wenn `params.authoring === true`
  **und** die Controls sichtbar werden (gleicher Zeitpunkt wie
  `els.controls.hidden = false` nach erfolgreichem Load) — im Fehler- oder
  Vor-Load-Zustand bleibt der Button verborgen.
- Klick-Handler:
  1. `viewer.getPose()` lesen.
  2. Aktuelle `viewer.isAutoOrbit()` lesen.
  3. Ziel-URL bauen: bestehende `src`/`poster`/`autoplay`-Query-Werte aus
     `location.search` übernehmen, `pose=<6 Werte, 3 Nachkommastellen>` und
     `orbit=<0|1>` setzen/überschreiben, `authoring` **entfernen** (die kopierte
     URL ist für Endnutzer gedacht, nicht für weiteres Authoring).
  4. `navigator.clipboard.writeText(url)`; Button-Text wechselt kurz (z. B. 1,5 s)
     zu „Kopiert!" als Feedback, danach zurück zum Ausgangslabel.
- Kein neues Overlay/Toast-Element — das Feedback läuft komplett über den
  Button-Text, konsistent mit dem bestehenden minimalen Chrome-Stil.

## Fehlerbehandlung

- Ungültiger `pose`-Wert (falsche Anzahl Werte, nicht-numerisch): wird beim
  Parsen zu `null` und dadurch stillschweigend ignoriert — Auto-Frame greift,
  kein Error-Card, keine Konsolen-Warnung nötig (konsistent mit dem tolerant-
  stillen Umgang von `sceneLabel(null)` in der Basis-Spec).
- `navigator.clipboard` nicht verfügbar (z. B. kein sicherer Kontext): Klick auf
  „Pose kopieren" fällt auf `document.execCommand('copy')` via temporärem
  `<textarea>` zurück; schlägt auch das fehl, bleibt der Button-Text kurz auf
  „Kopieren fehlgeschlagen" stehen.

## Tests

- **Unit (`params.test.mjs`, `pose.test.mjs`):**
  - `parsePose`: gültige 6er-Liste → Array von Floats; falsche Arity → `null`;
    nicht-numerische Werte → `null`; Whitespace/führende Nullen tolerant.
  - `parseParams`: `orbit` Default `true`, `orbit=0` → `false`, beliebiger anderer
    Wert → `true`; `authoring` exakt `'1'` → `true`, sonst `false`.
- **E2E (Ergänzung `embed-smoke.test.mjs` oder neue Datei):**
  - `?authoring=1` mit kaputter `src`: Copy-Button bleibt während Error-State
    verborgen (Controls werden nie sichtbar) — verifiziert, dass der Button an
    denselben Sichtbarkeits-Gate wie `#controls` gekoppelt ist.
  - Ohne `authoring`-Param: `#btn-copy-pose` bleibt in jedem DOM-Zustand
    `hidden` (Element existiert, ist aber nie sichtbar).
  - Reales Laden + Klick-Verifikation des Copy-Flows (Pose-Werte landen korrekt
    in der gebauten URL) ist **kein** Teil der headless-E2E-Suite — wie in der
    Basis-Spec begründet, ist headless-GL kein Fidelity-Referenzpunkt und die
    bestehende Suite lädt bewusst keine echten Szenen. Diese Prüfung ist Teil
    des manuellen Smokes (siehe unten).
- `cd embed && ./tests/run.sh` muss vor jedem Commit grün sein.

## Manueller Smoke (Ergänzung zum bestehenden Task-7-Smoke)

- `?authoring=1&src=…`: Szene laden, frei orbiten/zoomen, „Pose kopieren"
  klicken → Zwischenablage enthält eine vollständige, gültige Embed-URL.
- Diese URL in neuem Tab öffnen (ohne `authoring`): Szene erscheint sofort in
  der zuvor gewählten Ansicht, kein Auto-Frame-Sprung.
- Dieselbe URL mit angehängtem `&orbit=0`: Kamera bleibt nach dem Laden exakt
  auf der kopierten Pose stehen, kein Auto-Orbit.

## Repo-Integration

- `embed/AGENTS.md`: Abschnitt „Architecture principles" um die drei neuen
  Parameter ergänzen (`pose`, `orbit`, `authoring`).
- Root-`CHANGELOG.md`: Eintrag unter `[Unreleased]` als Ergänzung zum bestehenden
  `embed/`-Eintrag (nicht als neuer Punkt — derselbe Slice/Release-Zyklus).

## Bewusst außerhalb des Scopes

- Numerisches Eingabefeld für Pose-Werte (Tippen statt interaktivem Orbiten).
- Presets/Speicherung mehrerer Posen pro Szene.
- Server-seitige Kurz-URLs für die (potenziell lange) Pose-Query-String.
- Undo/Reset-Button im Authoring-Modus (Reload der Seite genügt, um zur
  Auto-Frame-Ausgangslage zurückzukehren).
