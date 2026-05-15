# PLY Output Format Reference

Brush exports 3D Gaussian Splats in the **INRIA/Kerbl et al. PLY format** — the de-facto standard since the original 3DGS paper. This doc covers what's in the file, how to identify it, and which downstream tools can read it.

## Format identification

```bash
file scene.ply
# scene.ply: PLY model, binary, little endian, version 1.0
```

The first three header lines from a Brush v0.3.0 export:

```
ply
format binary_little_endian 1.0
comment Exported from Brush
comment Vertical axis: y
comment SH degree: 3
element vertex 82172
```

## Properties — 59 floats per gaussian (at SH degree 3)

| Group              | Count | Properties              | Meaning                                         |
| ------------------ | ----: | ----------------------- | ----------------------------------------------- |
| Position           |     3 | `x`, `y`, `z`           | World-space mean                                |
| Anisotropic scale  |     3 | `scale_0..2`            | Per-axis scale (log-space in some variants)     |
| Rotation           |     4 | `rot_0..3`              | Quaternion `(w, x, y, z)` or `(x, y, z, w)` — varies per producer; Brush uses `(w, x, y, z)` |
| Opacity            |     1 | `opacity`               | Pre-sigmoid logit                               |
| SH DC term         |     3 | `f_dc_0..2`             | View-independent RGB base                       |
| Higher-order SH    |    45 | `f_rest_0..44`          | View-dependent colour coefficients (SH=3)       |

Total: **3 + 3 + 4 + 1 + 3 + 45 = 59 floats × 4 bytes = 236 bytes/gaussian** at SH degree 3.

For other SH degrees:

| SH degree | f_rest count | Total per-gaussian bytes |
| --------- | -----------: | -----------------------: |
| 0         |            0 |                       56 |
| 1         |            9 |                       92 |
| 2         |           24 |                      152 |
| **3**     |       **45** |                  **236** |

Formula: `f_rest_count = 3 · ((sh_degree + 1)² − 1)`.

The Phase-4 `obsidian.read_ply_header()` infers `sh_degree` from the comment when present, else from `f_rest` count.

## Size in practice

| Capture     | Gaussians | SH | File size | Notes                                           |
| ----------- | --------: | -: | --------: | ----------------------------------------------- |
| bench_chill |    82 172 |  3 |   19.4 MB | Phase-0 baseline, 21.5 s 4K source              |

Rule of thumb: **PLY size (MB) ≈ gaussians × 236 / 1 048 576**.

## Coordinate system

- `comment Vertical axis: y` — Brush exports Y-up
- COLMAP-OPENCV camera model
- Right-handed coordinates

Viewers that assume Z-up (Blender, MeshLab) will render the scene rotated 90° on import. SuperSplat / PlayCanvas / gsplat.studio respect the comment.

## Viewer compatibility

| Viewer                    | Reads INRIA PLY | Reads compressed (SOG/SPZ) | Notes                                                                                       |
| ------------------------- | :-------------: | :------------------------: | ------------------------------------------------------------------------------------------- |
| **SuperSplat**            | ✅              | ✅                         | Browser, primary cleanup + publish tool. <https://playcanvas.com/supersplat/editor>         |
| **PlayCanvas Viewer**     | ✅              | ✅                         | Browser, lighter weight, embed-friendly                                                     |
| **gsplat.studio**         | ✅              | ✅                         | WebGPU, mobile-friendly                                                                     |
| **Brush built-in viewer** | ✅              | ❌ (Brush exports raw PLY) | `brush <ply> --with-viewer` — same engine as the trainer                                    |
| **antimatter15/splat**    | ✅              | ⚠️ partial                | Vanilla Three.js, good for embedding in custom pages                                        |
| **Three.js GaussianSplats3D** | ✅          | ✅ (KSPLAT)                | <https://github.com/mkkellogg/GaussianSplats3D>                                              |
| **Niantic SPZ viewer**    | ⚠️ (via convert) | ✅                         | Niantic's web viewer                                                                        |
| **Blender 3DGS add-on**   | ⚠️              | ❌                         | Reads positions + colour, ignores anisotropic scale + SH                                    |
| **MeshLab / classic PLY** | ⚠️              | ❌                         | Renders as a point cloud — splat properties ignored                                         |

## Compressed format comparison

`autosplat compress <ply> --format <fmt>` (Phase 5) wraps PlayCanvas's
`splat-transform` via `npx` for SOG and SPZ. KSPLAT output is NOT supported
by `splat-transform` — that format requires the mkkellogg/GaussianSplats3D
converter, which we don't currently wire in.

### Measured ratios on the Phase-0 `bench_chill` PLY

Input: 19.4 MB, 82 172 Gaussians, SH degree 3.

| Format | Quality   | Output size | Ratio | Reduction | Wall-time |
| ------ | --------- | ----------: | ----: | --------: | --------: |
| SOG    | high      |    3.58 MB  |  0.185|     82 %  |    20.6 s |
| SOG    | medium    |    3.58 MB  |  0.185|     82 %  |    16.1 s |
| SOG    | low (SH=1)|    1.72 MB  |  0.089|     91 %  |     5.1 s |
| **SPZ**| medium    |  **1.87 MB**|  0.097|   **90 %**|   **1.3 s**|
| KSPLAT | —         |          —  |    —  |       —   |        —  |

**Notes:**
- SOG `high` vs `medium` produces near-identical output size — the extra
  iterations converge at this gaussian count. `medium` is the sweet spot.
- SOG `low` filters spherical harmonics down to SH=1, cutting view-dependent
  colour but halving size. Use when the splat is meant for distant views.
- SPZ produces the smallest medium-quality output and is **~12× faster** than
  SOG — useful for batch workflows. Loader compatibility is narrower
  (Niantic viewer, Three.js with shims) so for SuperSplat-native workflows
  SOG is still primary.
- KSPLAT was originally in scope but `splat-transform` only reads `.ksplat`,
  it doesn't produce it. Wire-up of the mkkellogg toolchain is Phase-6+ work.

### Format-selection guide

| Use case                                                  | Recommended format |
| --------------------------------------------------------- | ------------------ |
| Obsidian Publish iframe / SuperSplat web embed            | **SOG (medium)**   |
| Three.js Web page (own loader)                            | SPZ                |
| Quick preview share (size > quality)                      | SOG (low) or SPZ   |
| Archive / re-edit later                                   | keep raw PLY       |

For embedding in an Obsidian Publish iframe or a Web page, **SOG via SuperSplat's browser-export is the lowest-friction path** — no CLI installation needed. `autosplat compress` is the scriptable equivalent for batch workflows.

## Reading the header yourself

```python
def read_ply_meta(path):
    with open(path, "rb") as f:
        for raw in f:
            line = raw.decode("ascii", errors="ignore").rstrip()
            if line.startswith("element vertex "):
                n = int(line.split()[-1])
            if line == "end_header":
                break
    return {"gaussians": n}
```

Quick CLI inspection:

```bash
awk '/^end_header/{exit} {print}' scene.ply | head -30
```

The file is little-endian binary after `end_header`; each gaussian record is exactly `total_properties × 4` bytes laid out in property order.

## Pure-Python inspection helpers in this repo

- `src/autosplat/export.py::validate_ply()` — header-magic + min-size check
- `src/autosplat/obsidian.py::read_ply_header()` — pulls `gaussian count` + `sh_degree` (from comment or by inference)

## References

- Kerbl et al., *3D Gaussian Splatting for Real-Time Radiance Field Rendering*, SIGGRAPH 2023 ([paper](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/))
- INRIA original code base (defines the PLY layout)
- Brush: <https://github.com/ArthurBrussee/brush>
