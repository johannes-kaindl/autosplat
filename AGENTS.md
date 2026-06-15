# AGENTS.md

> **Workspace-Standards:** Die verbindliche Leitkonvention steht in `_docs/CONVENTIONS.md`
> (am Workspace-Root `/Users/Shared/code/`), Modell comply-or-explain.

Guidance for AI coding agents working in this monorepo.

## What this is

`autosplat` ist ein **Monorepo** der beiden zusammengehörigen AutoSplat-Komponenten:

| Pfad | Inhalt | Eigene AGENTS.md |
|---|---|---|
| `pipeline/` | Lokale Pipeline: Drohnen-/Handheld-Video → trainierter 3D Gaussian Splat (Python, uv, Apple-Silicon-only) | `pipeline/AGENTS.md` |
| `viewer/` | Statische Viewer-PWA für Gaussian Splats (Vanilla HTML/CSS/JS, kein Build-Step) | `viewer/AGENTS.md` |

**Regel:** Für Arbeit *innerhalb* einer Komponente gilt deren eigene AGENTS.md — dort
stehen Befehle, Test-Pflichten, Commit-Stil und Architektur-Notizen. Diese Datei regelt
die Produkt-Ebene darüber.

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
  `cd viewer && ./tests/run.sh`.
- **Pages-Deploy des Viewers:** `scripts/deploy-pages.sh` (subtree split `viewer/` →
  `pages`-Branch). Live: `https://jkaindl.codeberg.page/autosplat/`.

## Memory + session state

- **Session-Handoff** (sessionübergreifend, in diesem Repo): `.remember/` — `remember.md`
  (Handoff), `now.md` (Buffer), `today-*.md`, `recent.md`, `archive.md`, `core-memories.md`.
  `.remember/` ist Arbeitspuffer und gitignored.
- **Persistentes Memory** (außerhalb des Repos):
  `~/.claude/projects/-Users-Shared-code-autosplat/memory/`
- **Coding-Cockpit** (Status/Tasks/History) im Pallas-Vault:
  `10_Pallas/25_Coding/autosplat/autosplat.md`.
