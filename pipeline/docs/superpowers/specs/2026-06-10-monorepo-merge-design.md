# Design: Monorepo-Merge `autosplat`

**Datum:** 2026-06-10
**Status:** Vom Maintainer abgenommen
**Betrifft:** `autosplat-pipeline` + `autosplat-viewer` → ein Monorepo

## Motivation

Die beiden Repos sind eng gekoppelt (Pipeline exportiert Splats, Viewer lädt sie),
werden aber getrennt gepflegt. Konkrete Schmerzen, die der Merge löst:

1. **Interface-Drift** — Exportformat (Pipeline) und Loader (Viewer) laufen
   auseinander; Format-Änderungen brechen den Viewer unbemerkt.
2. **Kein gemeinsamer E2E-Test** — es fehlt ein Test „Pipeline-Output → lädt im
   Viewer"; Fixtures sind doppelt gepflegt.
3. **Doppelter Verwaltungsaufwand** — zwei CHANGELOGs, zwei Release-Prozesse,
   zwei Issue-Tracker, doppelte Meta-Dateien.
4. **Gemeinsame Features geplant** — kommende Änderungen betreffen beide Seiten
   und brauchen atomare Commits.

Klassische Monorepo-Gegenargumente treffen hier nicht: identisches Lizenzmodell
(AGPL-3.0 + Dual-Licensing/CLA), ein einziger Maintainer, und die bisherige
Codeberg-Pages-URL des Viewers darf brechen (vom Maintainer freigegeben).

## Verworfene Alternativen

- **Getrennt lassen + Contract-Tests/Format-Spec:** löst Drift und E2E nur
  teilweise, Verwaltungsaufwand und atomare Commits gar nicht.
- **Submodule-Umbrella:** Submodule-Reibung statt atomarer Commits.

## Zielstruktur

```
autosplat/                  (Codeberg: jkaindl/autosplat — lokal: /Users/Shared/code/autosplat)
├─ README.md, CHANGELOG.md, AGENTS.md          ← neu am Root (Produkt-Ebene)
├─ LICENSE, LICENSING.md, CLA.md, SECURITY.md,
│  CITATION.cff, CONTRIBUTING.md               ← konsolidiert; bei Textabweichungen
│                                                bleibt die abweichende Datei im Unterordner
├─ scripts/deploy-pages.sh                     ← Viewer-Deploy (subtree split → pages)
├─ pipeline/   ← kompletter Inhalt des bisherigen Pipeline-Repos, intern unverändert
└─ viewer/     ← kompletter Inhalt des bisherigen Viewer-Repos, intern unverändert
```

Innerhalb der Unterordner ändert sich nichts — alle relativen Pfade, Tests und
Skripte funktionieren weiter. Die bisherigen CHANGELOGs bleiben als Historie in
den Unterordnern; das Root-CHANGELOG startet mit v1.12.0. Die jeweilige
AGENTS.md bleibt pro Unterordner erhalten (Konventionen pro Komponente), die
Root-AGENTS.md regelt die Produkt-Ebene.

## History-Merge (verlustfrei)

1. Frische Klone beider Repos (Arbeitskopien bleiben unangetastet als Backup).
2. Pro Klon: `git filter-repo --to-subdirectory-filter pipeline` bzw. `viewer`
   mit `--tag-rename '':'pipeline-'` bzw. `'':'viewer-'`.
   - Verschiebt die gesamte History in den Unterordner.
   - Löst die Tag-Kollision (beide Repos haben `v1.1.0`/`v1.1.1`):
     historische Tags heißen künftig `pipeline-v*` / `viewer-v*`.
   - Nimmt den offenen Branch `feat/collision-mesh` (8 eigene Commits)
     automatisch mit. `feat/service-portfolio` ist vollständig in main
     gemergt und entfällt.
3. Neues Repo, beide gefilterten Histories per
   `git merge --allow-unrelated-histories` auf `main` zusammenführen.

Voraussetzung: `git-filter-repo` (brew).

## Versionierung & Releases

- **Eine gemeinsame Version** ab `v1.12.0` (Fortsetzung des Pipeline-Strangs;
  der Viewer springt von 1.1.1 mit).
- Ein Root-CHANGELOG (Keep-a-Changelog), ein Release-Tag `vX.Y.Z` für beides,
  Codeberg-Release via API wie bisher.
- Der offene Punkt PROF-NAT-02 (version-bump-Script pyproject ↔ Info.plist)
  wird dadurch einfacher: eine Versionsquelle.

## Pages-Deploy des Viewers

- `scripts/deploy-pages.sh`: `git subtree split --prefix viewer` → Push auf den
  `pages`-Branch des Monorepos.
- Neue URL: `jkaindl.codeberg.page/autosplat/…` — Delivery-Links (`?src=`) und
  Verweise in README/Doku werden angepasst. Alte URL bricht (freigegeben).

## Codeberg-Umzug

1. Neues Repo `jkaindl/autosplat` anlegen (Gitea-API), Beschreibung/Topics/
   Website übertragen.
2. `main`, Tags und `feat/collision-mesh` pushen; Pages-Deploy ausführen und
   verifizieren.
3. Alte Repos (`video-to-3d-gaussian-splat`, `autosplat-viewer`)
   **archivieren** (nicht löschen), vorher Umzugshinweis ins README.
4. Offene Issues einmalig manuell übertragen (Maintainer-Entscheidung pro Issue).

Lokal wird `/Users/Shared/code/autosplat` selbst zum Monorepo (passt zum
bestehenden `.remember`- und Memory-Pfad). Die alten lokalen Klone bleiben bis
zur Verifikation als Backup liegen.

## Verifikation (Definition of Done)

- [ ] `uv run pytest -q` in `pipeline/` grün
- [ ] `./tests/run.sh` in `viewer/` grün
- [ ] Volle History beider Repos per `git log --follow` in den Unterordnern erreichbar
- [ ] Historische Tags als `pipeline-v*` / `viewer-v*` vorhanden
- [ ] `feat/collision-mesh` im Monorepo vorhanden (8 Commits)
- [ ] Pages-Deploy durchgespielt, Viewer-URL im Browser geprüft
- [ ] Alte Codeberg-Repos archiviert mit Umzugshinweis

## Bewusst nicht in Scope (Follow-ups)

- Gemeinsamer E2E-Test: Pipeline-Export → Puppeteer lädt ihn im Viewer
  (der eigentliche Verzahnungs-Gewinn — eigenes Feature nach der Migration).
- Konsolidierung der offenen Konventions-Punkte beider AGENTS.md
  (CORE-GIT-01, CORE-AGENT-01/04, PROF-NAT-02/03).
- Vereinheitlichtes version-bump-Script.

## Risiken

- **Tag-/Release-Verweise:** Bestehende Codeberg-Releases hängen an den alten
  Repos; sie bleiben dort über die Archivierung erreichbar.
- **Memory-Pfade:** Das Viewer-spezifische Claude-Memory
  (`~/.claude/projects/-Users-Shared-code-autosplat-viewer/memory/`) wird nach
  dem Merge nicht mehr automatisch geladen — relevante Inhalte (z. B.
  `codeberg-release-workflow`) ins `-autosplat`-Memory übernehmen.
- **subtree split Performance:** unkritisch bei dieser Repo-Größe; der
  `pages`-Branch ist reines Deploy-Artefakt (force-push erlaubt).
