# PHASE-9-RECON — SuperSplat Local + WebUI Options

*Recon-Burst 2026-05-14 · Status: **Decision-Gate** · Autor: CC-Executor*

---

## 1 · SuperSplat-Source-Recon

**Lizenz:** MIT — vollständig Open Source, uneingeschränktes Self-Hosting und Modifikation erlaubt.

**Repo:** [github.com/playcanvas/supersplat](https://github.com/playcanvas/supersplat)

**Build-Stack:**
- Rollup 4.60.3 (Bundler), TypeScript 6.0.3, SCSS/PostCSS
- Node.js ≥ 20.19.0 erforderlich
- PlayCanvas Engine 2.18.1 (WebGL/WebGPU-Renderer)

**Dev-Server:**
- `npm run develop` → concurrent Rollup-Build + Dev-Server auf **Port 3000** (`http://localhost:3000`)
- `npm run serve` → Server-only (kein Live-Rebuild), ebenfalls Port 3000
- `npm run build` → Production-Bundle nach `dist/`

**Bundle-Größe:** Nicht offiziell dokumentiert. Typisch für Rollup+TS SPAs mit WebGPU-Engine: 2–8 MB minified+gzip. Muss nach lokalem Build verifiziert werden.

**Headless-Mode:** **Keiner.** Kein CLI-Modus, keine programmatische PLY-Import-API. Die Applikation ist rein browser-interaktiv (Drag-and-drop oder File-Open-Dialog). Eine maschinelle Batch-Verarbeitung ist nicht vorgesehen.

**URL-Parameter:** SuperSplat unterstützt einen `?load=<URL>`-Parameter (bestätigt aus `main.ts`: `url.searchParams.getAll('load')`). Die App fetcht die URL über `fetch()` beim Start. Bedeutung für die Pipeline: ein lokal laufendes SuperSplat kann so eine lokal servierte PLY-Datei automatisch laden — ohne manuellen Drag-and-drop.

---

## 2 · Local-Server-Integration-Options

Drei Ansätze, SuperSplat lokal zu betreiben:

| Kriterium | **(a) Static-Build im Repo** | **(b) `file://`-iframe** | **(c) Electron-Wrapper** |
|---|---|---|---|
| Beschreibung | SuperSplat-Repo clonen, `npm run build`, `dist/` statisch via uvicorn/http.server ausliefern | SuperSplat-`dist/` lokal bauen, `file://`-URL in Obsidian | SuperSplat in Electron-App wrappen |
| Dev-Aufwand | Mittel (Node-Setup + Build-Step in Install-Script) | Niedrig (nur Build) | Hoch (Electron-Packaging) |
| CORS/Mixed-Content | ✅ **OK** — `http://localhost:3000 → http://localhost:8765` = same-scheme, kein Mixed-Content | ⚠️ Browser-abhängig — `file://`-Seiten dürfen in neueren Chrome/Safari-Versionen keine `http://` fetchen | ✅ OK (Electron-Native) |
| Obsidian-Embed (`iframe src`) | ✅ `http://localhost:PORT?load=...` funktioniert im Reading-Mode | ❌ `file://`-URLs in Obsidian-iframes blockiert | ❌ keine iframe-Kompatibilität |
| Nutzer-Voraussetzungen | Node.js + npm (einmalig via Install-Script) | Node.js + npm (nur für Build) | Kein Node nach Build |
| Update-Wartung | SuperSplat-Updates: `git pull && npm run build` | Identisch | Hoch (Electron-Releases) |
| Sharing/Mobile | ❌ `localhost`-URL nicht teilbar | ❌ | ❌ |
| **Fazit** | **Empfohlen für Phase 9** | Machbar für reinen Viewer, kein Obsidian-Embed | Overengineering für diesen Scope |

**Wichtige CORS-Klarstellung:** Der aktuelle `viewer.py`-Code öffnet `https://playcanvas.com/supersplat/editor?load=http://127.0.0.1:8765/scene.ply`. Das ist **nachweislich broken**: Ein HTTPS-Dokument (playcanvas.com) darf aus Sicherheitsgründen keine HTTP-Ressource (127.0.0.1) fetchen (Mixed-Content-Blockierung). Die `?load=`-Funktion existiert in SuperSplat, war aber de facto nie nutzbar mit der aktuellen remote-Viewer-Konfiguration.

---

## 3 · Web-UI-Scope-Achsen

Was würde eine lokale Web-UI über das CLI hinaus bieten? Bewertung nach Phase-9-Relevanz:

| Feature | Beschreibung | Phase-9-Pflicht? | Begründung |
|---|---|---|---|
| **(a) Drop-Zone** | Video ins Browser-Fenster ziehen → startet Pipeline | Nein | CLI `autosplat watch` erfüllt das. Dopplung ohne zusätzlichen Nutzen. |
| **(b) Live-Pipeline-Status** | Fortschritt der laufenden Stage, ETA, Logs | Nein | `autosplat status` + Rich-Terminal reichen. WebUI-Polling erhöht Komplexität ohne echten Vorteil gegenüber Terminal-Tab. |
| **(c) Capture-Browser** | Liste aller Captures mit FM-Stats (Gaussians, Datum, PLY-Größe) | **Ja (Phase 9)** | Direkte Abhilfe für den "Wo ist mein Capture?"-Pain (s. §11). Obsidian Bases sind alternative, aber eine autosplat-native Ansicht wäre wertvoller für den Viewer-Launch-Flow. |
| **(d) Inline-SuperSplat-Editor** | SuperSplat als iframe in der Web-UI | Optional | Funktioniert, aber `localhost:3000` direkt zu öffnen ist genauso gut. Iframe fügt nichts hinzu. |
| **(e) "Save to Obsidian"-Button** | Füllt `embed_url:` + `embed_view_url:` in der Capture-Note nach Cleanup | **Ja (Phase 9)** | Adressiert den #1 Pain-Point: leere `embed_url` nach Pipeline-Run. |
| **(f) Doctor-Status-Pane** | Deps-Status im Browser | Nein | `autosplat doctor` reicht vollständig. |

**Minimaler Phase-9-Web-UI-Scope** (falls WebUI gebaut wird): Capture-Browser-Liste + "In SuperSplat öffnen"-Button + "embed_url in Obsidian Note schreiben"-Button. Alles andere ist Phase 10+.

---

## 4 · iframe-Target-Strategie

Drei Ansätze für den `embed_url`-Wert in Obsidian-Capture-Notes:

| Strategie | Beispiel-URL | Pros | Cons |
|---|---|---|---|
| **localhost:PORT** (lokal) | `http://localhost:3000?load=http://localhost:8765/burgstall/scene.ply` | Funktioniert offline, kein Cloud-Upload nötig, automatisierbar | Nur auf demselben Rechner nutzbar; Obsidian-Mobile sieht leeren iframe; nicht teilbar |
| **superspl.at Share-URL** (cloud) | `https://superspl.at/s?id=09cbbcd9` | Teilbar, mobile-kompatibel, kein lokaler Server nötig | Erfordert manuellen Cloud-Upload via Browser; keine bekannte API; PlayCanvas-Cloud-Abhängigkeit |
| **Standalone-HTML-Export** | `file:///Users/.../burgstall-viewer.html` | Vollständig offline + lokal | `file://`-URLs in Obsidian-iframes blockiert; Dateigröße unklar; SuperSplat unterstützt keinen Standalone-HTML-Export |

**Empfehlung:** Zweistufige Strategie:
1. **`embed_url` = localhost-URL** — automatisch befüllt nach Pipeline-Run, sofort nutzbar auf dem Arbeitsrechner.
2. **`embed_view_url` = superspl.at-URL** — manuell nach Cloud-Upload eingetragen, optional.

Das Obsidian-Note-Template sollte beide Felder mit einem Fallback-Link vorsehen: zeige iframe wenn `embed_url` gesetzt, zeige "In SuperSplat öffnen"-Link als Fallback.

---

## 5 · Obsidian-Reader-UX

**Wenn lokaler SuperSplat-Server läuft:** `iframe src="http://localhost:3000?load=..."` rendert vollständig interaktiv im Obsidian-Reading-Mode.

**Wenn Server nicht läuft:** iframe zeigt leere/gebrochene Seite ohne Fehlermeldung — schlechte UX. Mitigation: Note-Template sollte HTML-Fallback mit sichtbarem Hinweis enthalten:

```html
<iframe src="http://localhost:3000?load=..." ...></iframe>

> **Viewer offline?** Starte autosplat mit `autosplat serve` oder nutze den [Cloud-Link](https://superspl.at/s?id=XXXX).
```

**Screenshot-Preview-Fallback:** Phase 4 generiert keine Preview-Screenshots. Ein statisches `preview.jpg` (z.B. via Brush `--with-viewer` Screenshot-API oder FFmpeg-Thumbnailing) wäre ein niedriger Aufwand und macht die Note auch mobil/offline brauchbar. Kandidat für Phase 10.

**Mobile (Obsidian iOS/Android):** localhost-URLs funktionieren nie. Hier ist `embed_view_url` mit superspl.at-Link der einzige Weg. Ohne diesen bleibt die Note auf Mobile rein textlich.

---

## 6 · Auth + Sharing

**Out-of-Scope für Phase 9.** Kontext-Notiz für die Roadmap:

Der PlayCanvas Cloud Publish-Service (`superspl.at`) ist die einzige existierende Sharing-Lösung. Er ist an den PlayCanvas-Account gebunden und hat — soweit öffentlich bekannt — **keine offizielle API** für programmatisches Hochladen (kein REST-Endpoint, kein CLI-Tool dokumentiert). Ein automatisches "Publish + URL kopieren" wäre also ein Reverse-Engineering-Projekt.

Alternativen für Phase 10+:
- **Self-hosted Splat-Server** (z.B. nginx + statisches HTML mit Three.js/gaussian-splats-3d.js) → eigene Share-URLs auf eigenem Server/NAS
- **Obsidian Publish** — iframe-Rendering von externen Domains ist durch CSP eingeschränkt; superspl.at funktioniert (wie burgstall beweist), localhost-URLs nicht
- **Airdrop/Export** — `.ply` direkt teilen; Empfänger öffnet selbst in supersplat.com

---

## 7 · Tech-Stack-Implikationen

| Ansatz | Neue Runtime-Deps | Footprint | Setup-Komplexität | Test-Story |
|---|---|---|---|---|
| **Nur lokal SuperSplat** (Option A) | `node` + `npm` (System) | ~200 MB nach `npm install` | Mittel — `scripts/setup_supersplat.sh` | Smoke: `curl localhost:3000` + PLY-Load-Check |
| **FastAPI WebUI** (Option B) | `fastapi`, `uvicorn`, `jinja2` | ~15 MB pip | Mittel — neue `pyproject.toml`-Deps | Playwright oder `httpx`-basierte Tests |
| **`python -m http.server`** | Keine | Minimal | Trivial | N/A |
| **PyWebView** | `pywebview` | ~50 MB | Niedrig | Schwer automatisierbar |

**Beobachtung:** `python -m http.server` ist bereits via `socketserver.ThreadingTCPServer` in `viewer.py` implementiert — der HTTP-Server-Layer ist solved. Was fehlt ist lediglich (a) ein lokal laufendes SuperSplat und (b) eine CORS-konforme URL-Konstruktion.

FastAPI würde hauptsächlich dann Sinn ergeben, wenn das WebUI interaktive Endpunkte braucht (Pipeline-Trigger, Note-Update). Für reine statische Capture-Browsing-Pages reicht auch `http.server` + generiertes HTML.

---

## 8 · CLI-vs-WebUI-Hybrid

**Vorschlag für Spec §4 Repo-Struktur-Erweiterung** (Hybrid-Ansatz):

```
auto-splat-pipeline/
├── src/autosplat/
│   ├── viewer.py          # bestehend — fix CORS-Logik, add local-supersplat-path
│   ├── ui/
│   │   ├── server.py      # FastAPI/uvicorn app (optional, opt-in)
│   │   ├── templates/
│   │   │   └── captures.html   # Jinja2 Capture-Browser
│   │   └── static/
│   └── supersplat/        # ODER: target/supersplat/ (gitignored build-artifact)
└── scripts/
    └── setup_supersplat.sh  # clone + npm install + npm run build
```

**CLI-Erweiterung:**
```
autosplat serve [--port 8765] [--with-supersplat] [--open-browser]
```
- Ohne `--with-supersplat`: PLY-Server-only (wie heute, aber ohne remote-Viewer-Bug)
- Mit `--with-supersplat`: startet lokalen SuperSplat auf :3000 + PLY-Server auf :8765
- `autosplat watch` läuft unverändert parallel

**Separierung von Concerns:** `autosplat watch` und `autosplat serve` sind unabhängige Prozesse. Watch läuft dauerhaft im Hintergrund, serve ist interaktiv für Review-Sessions. Kein Kopplung.

---

## 9 · Test-Strategie

| Ebene | Ansatz | Coverage | Zeitaufwand |
|---|---|---|---|
| **Unit** | Mocks für SuperSplat-Process-Start, URL-Builder-Tests | URL-Konstruktion, Server-Start/Stop-Logic | Niedrig |
| **Integration** | `curl localhost:3000` nach `setup_supersplat.sh` + Server-Start | SuperSplat läuft + erreichbar | Mittel (erfordert npm im CI — problematisch) |
| **Playwright E2E** | Headless Chrome, lade PLY über localhost:3000, check canvas-Element | Echter PLY-Render | Hoch + langsam + CI-Infra-Aufwand |
| **Smoke (realistisch)** | `autosplat serve --with-supersplat --no-open`, curl-Check, dann manuell | Reachability | Niedrig |

**Empfehlung:** Für Phase 9 ist **Smoke-only** realistisch: Unit-Tests für URL-Builder + Process-Management + `curl`-basierter Smoke. Playwright wäre Gold-Standard aber unverhältnismäßig für diesen Scope. CI mit npm/Node ist lösbar aber erhöht Setup-Komplexität.

---

## 10 · Phase-Plan-Konsequenzen

### Option A — SuperSplat Local Auto-Open (~1–2 Tage)

Scope: Fix `viewer.py` (CORS-Bug), `scripts/setup_supersplat.sh` (clone + build), `autosplat serve --with-supersplat`, `embed_url`-Auto-Fill mit localhost-URL nach Pipeline-Run.

Adressiert direkt:
- CORS/Mixed-Content-Bug in `viewer.py` (PLY wurde nie wirklich automatisch geladen)
- `embed_url: ""` Problem — wird zu `http://localhost:3000?load=...`
- Manuelle Drag-and-drop-Pflicht entfällt

Nicht adressiert:
- Cloud-Share-URL für Mobile/Sharing
- Capture-Browser-Übersicht
- Keine neue UI außer Terminal

### Option B — Full Local WebUI (mehrere Tage, 4–8 Tage realistisch)

Scope: FastAPI-App mit Capture-Browser, Pipeline-Status, embedded SuperSplat iframe, "Obsidian Note Update"-Button, Doctor-Status-Pane.

Adressiert zusätzlich:
- Alle §3-Features (a)–(f)
- Bessere Onboarding-UX

Risiken:
- Scope-Creep — "nur noch ein Feature" kann Wochen verschlingen
- FastAPI als neue Runtime-Dep (nicht kritisch, aber `uv add`)
- Playwright-Tests oder manuelle Tests
- Zeit-zu-Nutzen-Ratio: die meisten Gains kommen aus Option A, nicht aus dem UI-Layer

### Option C — Hybrid: Local SuperSplat + Minimaler Capture-Browser (~2–3 Tage)

Option A + eine simple HTML-Seite (statisch generiert, kein Framework) mit Capture-Liste und "Open in SuperSplat" / "Update embed_url" Buttons. Kein Pipeline-Control im Browser.

**Decision-Gate-Kriterien:**
1. Wie häufig wird die Pipeline täglich genutzt? (weniger als 3× → A reicht)
2. Ist Mobile-Sharing/Obsidian-Mobile ein harter Requirement für Phase 9? (ja → Cloud-URL-Frage bleibt offen unabhängig von A/B/C)
3. Wie wichtig ist Capture-Browsing außerhalb von Obsidian? (Obsidian Bases deckt das bereits ab)

---

## 11 · Real-World-Use-Case-Friction

### Quellen: bench_chill Handover + burgstall Capture-Note

**Pain-Points aus der bench_chill Handover (manueller Roundtrip):**

1. **PLY-Load ist manuell** — Schritt 1 verlangt explizit Drag-and-drop in den Browser. Der `viewer.py`-`?load=`-Mechanismus funktioniert wegen Mixed-Content-Blockierung nicht (HTTPS→HTTP blockiert). Für bench_chill (19.4 MB) noch halbwegs schnell; für burgstall (214 MB) potentiell langsam.

2. **`embed_url` bleibt leer** — Die Obsidian-Note wird auto-generiert mit `embed_url: ""` und `embed_view_url: ""`. Jay muss nach dem Cloud-Publish manuell die URL ins Frontmatter eintragen. Das ist der einzige Schritt, der JSON-/YAML-Editierung in Obsidian erfordert — fehleranfällig und vergessbar.

3. **Cloud-Publish ist Pflicht für Obsidian-Embed** — Ohne superspl.at-Share-URL hat die Note keinen funktionierenden Viewer. Der gesamte "Obsidian-3D-Memory"-Workflow hängt an diesem einen manuellen Cloud-Upload-Schritt.

4. **SuperSplat-Cleanup ist genuiner Hand-Arbeit** — Floater-Entfernung und Crop sind naturgemäß manuell und können nicht automatisiert werden. Phase 9 sollte diesen Schritt explizit als "verbleibt manuell" framen — das ist kein Bug, das ist Intention.

**Pain-Points aus der burgstall-Note:**

5. **214 MB PLY — Upload-Zeit** — Ein 214 MB PLY in SuperSplat.com zu laden dauert im Browser erheblich länger als 19.4 MB (bench_chill). Ein lokaler SuperSplat (`http://localhost:3000?load=http://localhost:8765/scene.ply`) lädt von localhost — kein Netzwerk-Transfer, sofortige Verfügbarkeit.

6. **`embed_view_url: ""`** — Ein zweites Embed-URL-Feld existiert bereits in der Note (neben `embed_url`). Dessen Semantik ist unklar (editor vs. viewer?). Das Obsidian-Schema sollte für Phase 9 explizit definiert werden: `embed_url` = lokal (localhost), `embed_view_url` = cloud share.

7. **`total_duration_s: 3780` (~63 min)** — Bei langen Trainingsläufen sitzt Jay nicht am Rechner wenn das PLY fertig wird. Das Watch-Folder-Daemon-Modell (Phase 2) ist dafür gebaut — aber SuperSplat auto-open beim Pipeline-Ende wäre störend (unerwünschter Fenster-Popup nach 63 min). Eine **"fertig"-Notification** (macOS Notification Center) wäre wertvoller als Auto-Open. Kandidat für Phase 9 zusätzlich zu Option A.

**Was Phase 9 direkt adressieren sollte (priorisiert):**
1. PLY-Load-Automatisierung (lokaler SuperSplat + `?load=` funktioniert)
2. `embed_url`-Auto-Fill nach Pipeline-Run (localhost-URL, kein Cloud-Upload nötig)
3. Ggf. macOS Notification nach Trainingsende

---

## § Optionen-Matrix

| Dimension | **Option A** — SuperSplat Local Auto-Open | **Option B** — Full Local WebUI | **Option C** — Hybrid (A + Capture-Browser) |
|---|---|---|---|
| **Scope** | Fix viewer.py CORS + Setup-Script + embed_url-Auto-Fill | Komplette Web-App (Capture-Browser, Status, Inline-SuperSplat, Obsidian-Button) | Option A + statische Capture-Browser-Seite |
| **Zeitschätzung** | 1–2 Tage | 4–8 Tage | 2–3 Tage |
| **Tech-Stack** | Node.js (SuperSplat-Build), Python HTTP-Server (bereits vorhanden) | FastAPI + uvicorn + Jinja2 + Node.js | Node.js + simples generiertes HTML |
| **Test-Coverage** | Unit (URL-Builder) + Smoke | Unit + Integration + ggf. Playwright | Unit + Smoke |
| **Reader-UX (Obsidian)** | localhost-URL in embed_url — funktioniert auf Arbeitsrechner | Identisch + Cloud-URL-Button | Identisch wie A |
| **Mobile-UX** | ❌ (localhost nicht erreichbar) | ❌ (identisch — Cloud-URL bleibt manuell) | ❌ identisch |
| **Risiken** | npm/Node-Prerequisite; SuperSplat-Dev-Server muss laufen | Scope-Creep; neues Framework; längere Implementierungszeit | Moderat — HTML-Generierung einfach zu halten |
| **Konzeptpapier-Front-Reduktion** | Hoch — löst den CORS-Bug + eliminiert Drag-and-drop + füllt embed_url | Mittel-Hoch — zusätzlicher Wert gering vs. Aufwand | Hoch + marginale Capture-Browser-Verbesserung |
| **Adressiert Kern-Pain-Points (§11)** | #1, #2, #5, #7 | #1–#7 | #1, #2, #5, #6, #7 |

---

## § Architekt-Hypothese (explizit als Hypothese markiert — keine Empfehlung)

**Architekt-Hypothese (Jay/Cowork):** "Alles in einer Web-UI lokal vereinen" — Option B Full WebUI ist die richtige Richtung.

**CC-Gegenposition nach Recon:**

Die Hypothese ist konzeptionell kohärent, aber der Zeitaufwand ist unverhältnismäßig zu den zusätzlichen Gains über Option A hinaus. Die drei größten Pain-Points (PLY-Load-Friction, `embed_url` leer, 214 MB lokaler Transfer) werden alle durch Option A gelöst — der Web-UI-Layer fügt keine Lösung für diese Kern-Probleme hinzu, er fügt nur eine Alternative Darstellung hinzu (Browser statt Terminal).

**Kritischer Befund:** Das `embed_view_url: ""`-Problem (Cloud-Share-URL manuell) bleibt bei **allen** Optionen (A, B, C) offen, solange keine superspl.at-API existiert. Eine Full WebUI löst dieses Problem nicht. Das ist die Grenze, die Phase 9 ehrlich kommunizieren muss.

**Mobile-UX** ist die einzige Dimension, wo B/C gegenüber A einen echten Mehrwert hätte — aber auch B/C lösen das nicht, weil localhost-URLs auf Mobile nie funktionieren.

**CC-Hypothese:** Option A + macOS-Notification ist der effizienteste Zug für Phase 9. Option C (+ minimale Capture-Browser-Seite) wäre ein sinnvoller Bonus, wenn die Zieldefinition "etwas Visuelles für den Workflow-Überblick" beinhaltet. Option B sollte als Phase-10-Kandidat framed werden, wenn konkrete Nutzungsfeedback-Signale (mehr als 1 Person nutzt die Pipeline, mehr als 10 Captures pro Woche) vorliegen.

**Wenn die Architekt-Hypothese B bevorzugt:** Dann sollte der Plan B in Inkremente aufgeteilt werden — B₁ = Option A (1-2 Tage, sofort nutzbar), B₂ = Capture-Browser (1-2 Tage), B₃ = Pipeline-Control im Browser (2-3 Tage). Kein Big-Bang-B.
