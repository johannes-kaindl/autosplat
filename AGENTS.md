# AGENTS.md

> **Workspace-Standards (maintainer-lokal):** Die verbindliche Leitkonvention steht in `_docs/CONVENTIONS.md`
> im Multi-Projekt-Workspace des Maintainers, `../_docs` relativ zu diesem Repo — nicht Teil dieses Repos,
> ignorieren falls im Klon nicht vorhanden. Modell comply-or-explain.

Guidance for AI coding agents working in this monorepo.

## What this is

`autosplat` ist ein **Monorepo** der beiden zusammengehörigen AutoSplat-Komponenten:

| Pfad | Inhalt | Eigene AGENTS.md |
|---|---|---|
| `pipeline/` | Lokale Pipeline: Drohnen-/Handheld-Video → trainierter 3D Gaussian Splat (Python, uv, Apple-Silicon-only) | `pipeline/AGENTS.md` |
| `viewer/` | Splat-Viewer mit **Walking-Mode** (First-Person + Kollision) und die Projekt-Website auf Codeberg Pages (Vanilla HTML/CSS/JS, kein Build-Step) | `viewer/AGENTS.md` |
| `embed/` | Minimaler, embed-fähiger Splat-Viewer: iframe-Seite mit vendored Engine, zero-external | `embed/AGENTS.md` |

**Regel:** Für Arbeit *innerhalb* einer Komponente gilt deren eigene AGENTS.md — dort
stehen Befehle, Test-Pflichten, Commit-Stil und Architektur-Notizen. Diese Datei regelt
die Produkt-Ebene darüber.

## Rollen-Charta (ratifiziert 2026-07-29, nicht neu diskutieren)

**AutoSplat.app ist die kanonische Tür.** Jeder Schritt von Import bis Veröffentlichung
muss dort klickbar sein. Die CLI ist gleichwertig für Automatisierung und Batch, darf aber
**nie der einzige Weg** zu einem Schritt sein — und umgekehrt.

Die drei Viewer überlappen sich nur beim reinen Anschauen. Jeder hat genau eine Rolle:

| Artefakt | Rolle |
|---|---|
| SuperSplat (`pipeline/target/supersplat/dist`, gebündelt) | **bereinigen** — der Editor des Review-Gates |
| `embed/` | **teilen** — zero-external Runtime in Share-Bundles |
| `viewer/` | **begehen** — Walking-Mode; dazu die Projekt-Website |

Ein vierter Viewer ist eine Design-Entscheidung, kein Detail. Wer einen hinzufügt, trägt
ihn hier ein oder lässt es.

**Gebündelte Ressourcen, wie die App sie auflöst** — der WebUI-Mount
(`resources.viewer_status`/`_root_for`) und alles, was `create_app` und das gepackte
Bundle anfassen — laufen ausschließlich über `resources.bundled_path()`, nie gegen
`Path.cwd()`. Ein Finder-Start hat kein sinnvolles CWD; genau daran fehlte jeder DMG bis
v1.16.0 der Review-Viewer. Reine CLI-Pfade (`autosplat serve --with-supersplat`, die
Preflight-Warnung vor `process`/`resume`/`add-video`/`rescue`, deren Auto-Open am Ende)
dürfen einen relativ gesetzten `supersplat_dist_path`-Override weiterhin gegen das
Arbeitsverzeichnis auflösen — für ein Terminal-Kommando ist das erwartetes Verhalten,
kein Bug; sie laufen nie im gepackten Bundle.

## Working in the monorepo

- **Ein Git-Repo** für beides — repo-übergreifende Änderungen (z. B. Export-Format der
  Pipeline ↔ Loader des Viewers) gehören in **einen atomaren Commit** und werden im
  Root-`CHANGELOG.md` vermerkt; betrifft eine Änderung nur eine Komponente, deren
  Sub-CHANGELOG bleibt die Detailebene.
- **Schnittstelle:** die Pipeline exportiert komprimierte `.ply`-/Splat-Dateien, die der
  Viewer lädt. Format-Änderungen auf einer Seite immer gegen die andere prüfen.
- **Versionierung:** eine gemeinsame Version ab `v1.12.0` (ein Release-Tag `vX.Y.Z` für
  beides). Historische Tags sind `pipeline-v*` / `viewer-v*`.
- **Tests vor jedem Commit:** `cd pipeline && uv run pytest -q` bzw.
  `cd viewer && ./tests/run.sh` bzw. `cd embed && ./tests/run.sh`.
- **Pages-Deploy des Viewers:** `scripts/deploy-pages.sh` (subtree split `viewer/` →
  `pages`-Branch). Live: `https://jkaindl.codeberg.page/autosplat/`.

## Memory

> Dieser Abschnitt beschreibt das persönliche Claude-Code-Setup des Maintainers
> auf seiner eigenen Maschine — für andere Klone/Contributor irrelevant,
> einfach überspringen.

- **SDD-Artefakte (seit 2026-07-16): Cockpit, nicht Repo** — Specs/Plans/Task-Reports leben im
  Coding-Cockpit des Maintainers (`$VAULT/25_Coding/autosplat/_SDD/`, CORE-META-14, maintainer-lokal).
  Sie tragen Arbeitskontext (Vault-Pfade, Schwester-Repo-Interna), der in einem public Repo niemandem nützt.
  Das Repo behält die Design-Essenz in dieser Datei + `CHANGELOG.md`.
- **Alt-Bestand:** `pipeline/docs/superpowers/{specs,plans}/` und `viewer/docs/superpowers/plans/`
  sind eingefroren — nichts Neues dort ablegen.
- **Nie im Repo:** absolute Pfade außerhalb des Repos (`/Users/…`, Vault-Pfade) — Platzhalter nutzen
  (`$VAULT/…`, `~/…`, repo-relativ). Herkunftsnachweise als Repo-Name + `Datei:Zeile` sind dagegen erwünscht.
- **Session-Handoff** (sessionübergreifend, in diesem Repo): `.remember/` — `remember.md`
  (Handoff), `now.md` (Buffer), `today-*.md`, `recent.md`, `archive.md`, `core-memories.md`.
  `.remember/` ist Arbeitspuffer und gitignored.
- **Persistentes Memory** (außerhalb des Repos, nur auf der Maintainer-Maschine vorhanden):
  `~/.claude/projects/-Users-Shared-code-autosplat/memory/`
- **Coding-Cockpit** (Status/Tasks/History) im privaten Obsidian-Vault des Maintainers:
  `$VAULT/25_Coding/autosplat/autosplat.md`.
