# Embed-Viewer (`embed/`) — Design

**Datum:** 2026-07-14 · **Status:** approved · **Scope:** neue Monorepo-Komponente

## Ziel

Ein sauberer, eleganter, embed-fähiger Splat-Viewer als eigenständige iframe-Seite —
gebaut auf der bewährten Kern-Runtime des bestehenden Viewers, aber ohne dessen
Vermischung aus Landing-Page, Demo-Showcase und Experiment-Features. Primärer
Einsatz: Einbettung auf der eigenen Homepage (jkaindl.de) per
`<iframe src="…/embed/index.html?src=c/scene.sog">`.

Der bestehende `viewer/` bleibt **unangetastet geparkt** als Entwicklungsviewer
(Walking-Mode, Collision-Editor, Landing bleiben dort).

## Entscheidungen (mit dem Maintainer geklärt)

| Frage | Entscheidung |
|---|---|
| Embed-Form | **iframe-Seite** (kein Web Component; ggf. später als Wrapper) |
| Feature-Set | **Nur Auto-Orbit + Auto-Frame** (+ Fullscreen). Kein Walking, kein Collision-Editor, keine Dropzone, keine PWA |
| Struktur | **Neue Top-Level-Komponente `embed/`**, self-contained; bewusste kleine Kern-Duplikation statt Kopplung an den geparkten Dev-Viewer |
| Engine | **Vendored** (`vendor/playcanvas.mjs` 2.18.1 + `vendor/camera-controls.mjs`) — zero-external, keine Third-Party-Requests (Privacy-Invariante jkaindl.de) |
| UI | **Minimal-Chrome** mit Click-to-Load-Poster-Gate |
| Share-Bundle-Umstellung | **Folge-Slice**, nicht Teil dieser Arbeit — umgesetzt in `2026-07-15-share-bundle-embed-migration-design.md` |

## Dateilayout

```
embed/
  AGENTS.md            # Konventionen (Skelett nach CORE-AGENT-01)
  index.html           # die eine Embed-Seite (?src=…&poster=…&autoplay=1)
  css/embed.css
  js/
    main.js            # Shell: Poster-Gate, Controls, Fehler-UI, URL-Params
    viewer.js          # Kern-Runtime: Engine, Load, Auto-Frame, Auto-Orbit
    autoframe.js       # pure Perzentil-Framing-Mathe (unit-testbar)
  vendor/
    playcanvas.mjs     # ESM-Build aus dem npm-Package, Version eingefroren
    camera-controls.mjs
  tests/
    run.sh             # unit + e2e, Muster von viewer/tests
    unit/  e2e/
```

Vanilla ES-Module, **kein Build-Step** (Workspace-Konvention). Die Importmap in
`index.html` mappt `"playcanvas"` auf `./vendor/playcanvas.mjs`; dadurch löst auch
das vendored `camera-controls.mjs` seinen `playcanvas`-Import lokal auf.

## URL-Parameter-API

| Param | Pflicht | Wirkung |
|---|---|---|
| `src` | ja | Pfad/URL zu `.sog` oder `.ply` (same-origin, relativ oder absolut; `c/`-Delivery-Konvention kompatibel). Format-Detection über den Dateinamen (wie bisher `loadFromUrlAndFilename`) |
| `poster` | nein | Standbild fürs Klick-Gate; ohne Poster neutrale dunkle Karte mit Szenenname + Play |
| `autoplay` | nein | `1` überspringt das Gate und lädt sofort (für own-page above-the-fold) |

Ohne `src`: Hinweis-Karte („no scene specified") — **kein Demo-Fallback**, das
Embed ist kein Showcase.

## Verhalten

1. **Leichter Erstload:** wenige KB HTML/CSS/JS + Poster. Die Engine wird erst
   nach Klick per dynamic import geladen (kein ungefragter MB-Download, kein
   Scroll-/Touch-Hijacking der Host-Seite).
2. **Klick aufs Gate** → Engine laden → Splat laden → **Auto-Frame** (Perzentil-
   Logik aus `viewer/js/viewer.js` übernommen, floater-robust, 2,5 %-Quantile,
   Fallback auf Default-Pose wenn keine Center-Positionen verfügbar) →
   **Auto-Orbit** startet.
3. `prefers-reduced-motion` → Orbit startet pausiert. `pointerdown`/`wheel`
   pausiert Orbit (wie heute).
4. **Controls:** Orbit-Toggle, Fullscreen (inkl. iOS-Pseudo-Fullscreen-Fallback
   `body.fs-fallback`), dezentes „autosplat"-Badge als Link.

## Fehlerbehandlung

- **Load-Fehler:** ruhige Fehlerkarte im Frame mit Retry-Button — bleibt stehen
  (kein Auto-Hide-Timer, kein Alert).
- **Kein WebGL2:** Poster bleibt stehen + einzeiliger Hinweis; kein hartkodierter
  Fallback-Bildpfad.
- **Fehlendes/kaputtes `poster`:** Gate degradiert auf die neutrale Karte.

## Tests

Muster von `viewer/tests` (zero-dep `node:test` + auto-installiertes
`puppeteer-core`):

- **Unit:** URL-Param-Parsing; `autoframe.js`-Perzentil-Mathe (deshalb als pure
  Funktion herausgelöst — der eine Refactor gegenüber der heutigen Runtime).
- **E2E:** Gate-Klick → Canvas erscheint; `autoplay=1` lädt ohne Gate;
  Fehlerpfad (kaputte `src`) zeigt Fehlerkarte; ohne `src` Hinweis-Karte.
- `./tests/run.sh` muss vor jedem Commit grün sein.

## Repo-Integration

- Root-`AGENTS.md`: Komponententabelle bekommt die `embed/`-Zeile.
- `viewer/AGENTS.md` + `viewer/README.md`: Vermerk „geparkt als
  Entwicklungsviewer; der produktive Embed-Viewer lebt in `embed/`".
- Root-`CHANGELOG.md`: Eintrag unter `[Unreleased]`.
- Pages-Deploy bleibt unverändert `viewer/`; `embed/` wird durch Kopieren des
  Ordners gehostet (self-contained).

## Bewusst außerhalb des Scopes

- ~~Share-Bundle-Umstellung der Pipeline auf `embed/` als Bundle-Runtime~~ —
  umgesetzt, siehe `2026-07-15-share-bundle-embed-migration-design.md`.
- Einbindung auf jkaindl.de (Ordner kopieren + iframe setzen).
- Web-Component-Wrapper (`<autosplat-viewer>`).
- Walking-Mode im Embed (bewusst abgewählt, bleibt im Dev-Viewer).
