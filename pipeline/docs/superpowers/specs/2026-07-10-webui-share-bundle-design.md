# WebUI Share Bundle — Design

**Date:** 2026-07-10
**Status:** Approved (brainstorm), pre-implementation
**Scope:** pipeline WebUI (+ reads viewer static files)

## Problem

A finished capture produces a raw `output/scene.ply` (hundreds of MB — the LGS
test run was 619 MB / 2.75 M Gaussians). That file is not web-deliverable and
there is no in-product path to publish a scene. Compression exists only as a
manual CLI (`autosplat compress <ply> -f sog`); the WebUI has no equivalent to
its "View splat" action, and nothing packages a self-hostable, shareable view.

## Goal

Add an on-demand WebUI action on a **finished** capture — analogous to "View
splat" — that compresses the scene and assembles a **self-contained share
bundle**: a folder (and `.zip`) the user can drop onto any host under an
unguessable path, yielding a link anyone can open in the browser.

The security model is **unlisted** (unguessable URL), explicitly **not** access
control. Anyone with the link can view; no password, expiry, or revocation.
This is stated in the UI.

## Non-goals (YAGNI)

- SFTP / auto-deploy to a host — the user uploads the bundle manually.
- Access control (password / expiry / revocation / signed URLs).
- SPZ / KSPLAT output — SOG only for v1.
- Bundling the viewer into the frozen DMG app — v1 runs from the monorepo
  source checkout (`uv run autosplat webui`), where `../viewer` is reachable.
- Auto-compression as part of every pipeline run (a `[share]`/`[compress]`
  auto-flag can come later).

## User flow

1. On the detail page of a `done` capture, a new **"Web export · share"** card
   sits beside the View / PLY actions, with a **"Create share bundle"** button.
2. Click → a background job compresses + assembles; the card polls progress.
   The capture **stays `done`** — the main stepper / View button are untouched.
3. Done → the card shows:
   - `.sog` size + reduction % (e.g. "58 MB · 91 % smaller"),
   - **"Download bundle (.zip)"**,
   - the complete link `${base_url}/<token>/` with a copy button (or a
     host-agnostic template if `base_url` is unset),
   - a one-line caveat: *"Anyone with this link can view this model."*

## Architecture

### Components

**`autosplat/webui/share.py` (new)** — pure assembly logic, no FastAPI,
independently testable:

- `make_share_token(capture_id) -> str` — URL-safe, capture-name-derived prefix
  + random suffix (e.g. `lgs-pv-k7m2a9x4qz`). Unguessable suffix length ≥ 10
  base32 chars (~50 bits). Deterministic prefix, random suffix.
- `assemble_bundle(sog_path, viewer_src, dest_dir, token) -> BundlePaths` —
  copies the viewer runtime into `dest_dir/<token>/`, drops the splat at
  `<token>/c/scene.sog`, writes `<token>/index.html` (redirect →
  `viewer.html?src=c/scene.sog`), then zips to `dest_dir/<token>.zip`.
  Returns the folder path + zip path.
- `share_link(base_url, token) -> str | None` — `f"{base_url.rstrip('/')}/{token}/"`
  when `base_url` is set, else `None` (UI shows the host-agnostic template).

**Viewer runtime copy** — an allowlist of runtime files/dirs is copied:
`viewer.html`, `js/`, `css/`, `assets/`, `icons/`, `manifest.webmanifest`,
`service-worker.js`. Repo-meta is excluded: `tests/`, `docs/`, `index.html`
(landing), `c/` contents, `assets/demo/scene.sog` (the demo splat), licenses,
`AGENTS.md`, `package.json`, `*.md`, `.git`. Using an **allowlist** (not a
denylist) is safer against future stray files.

**`ShareJobRunner` (new, small)** — a dedicated in-memory registry keyed by
`capture_id`, independent of the pipeline `JobRunner`. One share job per
capture; status `running | done | failed`. Runs `compress_ply` +
`assemble_bundle` in a background `threading.Thread` so the ASGI loop is not
blocked. Deliberately separate so a share job never flips `capture.status` to
`running` and hide the finished view.

### Compression

Reuses the existing `compress_ply(ply, target_dir, fmt="sog", quality="medium")`
→ `CompressResult(output_path, output_bytes, input_bytes, ...)`. Backend is
splat-transform via npx, exactly as the CLI already does. No new compression
code.

### Routes (`routes/captures.py` + `routes/partials.py`)

- `POST /captures/{id}/share` — start a share job (409 if one already running
  for this capture), redirect back to the detail page.
- `GET /partials/capture/{id}/share` — poll partial: renders build progress
  while running; link + zip download + size/reduction when done; error on fail.
- `GET /captures/{id}/share/{token}.zip` — stream the assembled zip
  (`application/zip`, `Content-Disposition: attachment`). 404 if absent.

### GUI (`templates/capture/detail.html` + `partials/share.html`)

- New card gated to `capture.status == 'done'`, beside View / PLY.
- Before build: the "Create share bundle" button (POST form).
- After / during: the card body is the `share.html` partial, polled with
  `hx-get .../share` `hx-trigger="every 2s"` while the job is running; the poll
  stops once the job is terminal (the partial renders without a poll trigger).

### Config (`config.py` + `config/default.toml`, new `[share]` section)

```toml
[share]
base_url = ""                 # e.g. "https://splat.jkaindl.de"; empty → template
viewer_src_path = "../viewer" # relative to repo root (monorepo checkout)
quality = "medium"            # low | medium | high (splat-transform iterations)
```

`fmt` is fixed to `sog` in v1 (not a config knob yet).

### On-disk layout

Bundle lives under the capture so it is cleaned up with the capture:

```
<capture>/share/<token>/            # the self-contained site
<capture>/share/<token>/c/scene.sog
<capture>/share/<token>/index.html  # redirect → viewer.html?src=c/scene.sog
<capture>/share/<token>.zip         # download artifact
```

## Error handling

- No `output/scene.ply` → the card shows a disabled state / hint; POST returns
  400. (Only offered on `done` captures, so this is an edge case.)
- Compressor unavailable (`CompressorNotAvailable`) → job fails with the
  existing install hint surfaced in the card.
- `viewer_src_path` missing → job fails with a clear "viewer sources not found
  at <path>" message (the DMG-app limitation manifests here).
- Concurrent share request while one runs → 409.

## Testing (TDD, red first)

Unit (no npx — compression stubbed / `compress_ply` injected as a fake):

- `make_share_token` — URL-safe charset, stable prefix, random suffix length,
  two calls differ.
- `assemble_bundle` — correct tree (`<token>/`, `c/scene.sog`, `index.html`
  redirect target), allowlist honored (no `tests/`, no demo sog, no licenses),
  zip exists and contains the same tree.
- `share_link` — base_url set → complete trailing-slash link; unset → None.

Route (FastAPI `TestClient`, share job with a fake compressor):

- `POST /captures/{id}/share` starts a job and redirects; second POST while
  running → 409.
- `GET /partials/capture/{id}/share` renders the link + zip download + size
  when the job is done; shows progress while running; error when failed.
- `GET /captures/{id}/share/{token}.zip` downloads; unknown token → 404.
- The share job does **not** change `capture.status` (stays `done`).

## Open risks / notes

- **Frozen DMG app**: `viewer_src_path` won't resolve — documented v1
  limitation; a later slice can vendor the viewer runtime into the package.
- **splat-transform version**: `compress.py` pins `^2.1.1`; npx resolves that
  independently of any globally-installed v3. Unchanged by this feature.
- **Bundle size**: dominated by the `.sog` (tens of MB); the viewer runtime
  copy is a few hundred KB — negligible.
