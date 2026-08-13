# Seed: Kollisionsmesh aus Blender statt aus dem Browser-Voxelgitter

**Stand:** 2026-08-13 · **Herkunft:** Session im Repo `blender-lab`
(`/Users/Shared/40_Tools/blender`, HEAD `9b7a42e`) · **Status:** Briefing, kein Design.
Nichts davon ist hier ratifiziert — dieses Dokument ist nur der Kontext, damit die
nächste Session im Viewer nicht bei null anfängt.

## Worum es geht

Der Viewer baut sein Kollisionsmesh heute selbst: `collision-mode.js:41` voxelisiert
die Splat-Positionen auf ein **64³-Gitter** und lässt Marching Cubes drüberlaufen.
Für ein einzelnes Gebäude ist das passend. Für eine Straßenzeile nicht: die
Testszene (Augsburger Maximilianstraße, Capture `2026-05-26_max_strasse`) spannt
mehrere hundert Meter — 64³ bedeutet dort etwa **6 m Kantenlänge je Voxel**. Ein
Gehweg ist damit nicht auflösbar.

Parallel dazu ist in `blender-lab` eine Kette entstanden, die aus demselben PLY ein
Kollisionsmesh mit **1,5-m-Rasterzellen** erzeugt — Boden-Heightmap plus
Fassaden-Prismen, ohne Marching Cubes. Die Frage für den Viewer ist deshalb keine
Import-Fleißaufgabe, sondern eine Architekturentscheidung:

- **Datei-Loader neben dem eingebauten Pfad** — der Voxel-Editor bleibt für kleine
  Szenen, große Szenen kommen fertig aus Blender. Zwei Wege, die koexistieren.
- **Externer Weg ersetzt den internen** für alles ab einer bestimmten Szenengröße.
- **Auflösung im Viewer hochziehen** und den externen Weg gar nicht erst anfangen.

Vor Code lohnt hier Brainstorming. Der Viewer hat bereits `exportObj()`
(`collision-mode.js:95`) — ein *Import* fehlt, in beide Richtungen zu denken ist
also naheliegend.

## Was bereitliegt

Die Artefakte liegen **außerhalb dieses Repos**, beim Capture (bewusst: 7 MB
Binärlast passen nicht in ein Repo mit „kein Build-Step"-Philosophie):

```
/Users/johannes/AutoSplat/captures/2026-05-26_max_strasse/collision/
  collider_a010b.obj              7,0 MB — Original-Splat-Koordinaten, direkt andockbar
  max_strasse_collision_a010b.glb 4,5 MB — z-up, in Metern, für Blender/DCC
  coll_mesh_only_a010b.png        Sichtprüfung: grün = begehbar, braun = Hindernis
```

`collider_a010b.obj` ist der Import-Kandidat: die Rücktransformation in die
Original-Splat-Koordinaten ist bereits angewandt, das Mesh liegt also deckungsgleich
über der Punktwolke, die der Viewer lädt. Zwei Objekte, aneinandergehängt:
`ground_collision` (begehbare Fläche) und `wall_collision` (Hindernis-Prismen,
3 m hoch). Die OBJ-Datei hat keine Gruppen-Marker — falls der Viewer die beiden
trennen soll, muss `collision_mesh.py` das mitschreiben.

Erzeugt mit:

```bash
cd /Users/Shared/40_Tools/blender
./blr projects/splat/scripts/probe_ply.py <scene.ply> 5000000 0.1 subsample_a010.npz
./blr projects/splat/scripts/collision_mesh.py projects/splat/out/subsample_a010.npz a010b
```

## Zwei Befunde, die für den Viewer relevant sind

**1. Der Opazitätsfilter entscheidet über die Geometrie.** Ein 3DGS baut Oberflächen
aus vielen halbtransparenten Splats. Die Schwelle `alpha > 0,5` behält nur die 6 %
opaksten — texturarme Flächen wie Asphalt verschwinden dabei, kontrastreiche
Fassaden und Bäume bleiben. Ergebnis war ein Mesh, das zu 89 % aus Wand bestand und
dessen begehbare Fläche in 1.920 Fragmente zerfiel (größtes: 6 %). Mit `alpha > 0,1`
wird daraus eine dominante Komponente mit 76 %. Ganz ohne Schwelle kippt es zurück —
dann füllen Nebel-Splats den Luftraum.

Falls der Viewer beim Voxelisieren nach Opazität filtert oder gewichtet, ist das
derselbe Hebel — und dieselbe Falle.

**2. Die absolute Skala ist unbelegt.** Die Kette rechnet in Metern, aber der
Umrechnungsfaktor hängt an einer Annahme („höchste Struktur = St.-Ulrich-Turm,
93 m"). Die COLMAP-Posen der Capture sind nicht erhalten, und weil das Video
nachts entstand (`captured_at: 2026-05-26T22:39:56Z`), sind die oberen Fassaden zu
dünn rekonstruiert, um als Gegenprobe zu dienen. Der Anker ist inzwischen *stabil*
(5 % Streuung über die Opazitätsschwellen statt 16 %), aber ob 44,9 m je Splat-Unit
stimmt, weiß niemand.

**Das entscheidet sich im Walking-Mode.** Wenn sich das Gehen richtig anfühlt, ist
der Faktor richtig — und gehört dann fest in `M_PER_UNIT` in `collision_mesh.py`
(steht dort als `None` bereit). Fürs Erste ist jede Längenangabe im GLB mit dieser
Unsicherheit behaftet; das OBJ ist davon nicht betroffen, es liegt in
Splat-Koordinaten.

## Bekannte Schwächen des gelieferten Meshes

- **Ausschnitt statt Gesamtszene** — 400 × 400 m um das dichteste Fenster. Die
  Capture deckt km² ab, brauchbar rekonstruiert ist nur, wo die Kamera war.
- **Verdeckungslöcher** im Boden werden interpoliert gefüllt, nicht gemessen.
- **Wandhöhe pauschal 3 m** über dem lokalen Boden — reicht zum Anstoßen, ist aber
  keine Fassade.
- **Kein Dach, keine Innenräume.** Reine Außen-Begehbarkeit.

Ob das für den Walking-Mode reicht, zeigt erst der Rundlauf. Die Mesh-Qualität weiter
zu optimieren, bevor man einmal darin gelaufen ist, wäre Blindflug — deshalb endet
die blender-lab-Seite hier bewusst.

## Anknüpfpunkte im Repo

| Datei | Warum relevant |
|---|---|
| `js/collision/collision-mode.js` | `:41` Voxel-Pfad, `:95` `exportObj()`, `:117` Collider-Strategie |
| `js/collision/mesh-bvh.js` | `buildBvh(positions, indices)` — hier landet ein importiertes Mesh |
| `js/walking.js` | Collider-Switch: Heightmap ist Default, Mesh opt-in |
| `docs/superpowers/plans/2026-05-27-collision-mesh.md` | Der Plan, aus dem der Voxel-Pfad entstand |

Gegenstück auf der Blender-Seite: `projects/splat/scripts/collision_mesh.py` und der
numpy-Kern `lib/blab/splat.py` in `blender-lab`.
