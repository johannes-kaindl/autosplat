# Security Policy

## Scope

`auto-splat-pipeline` is a **local-first, single-user Mac tool**. It does not ship a hosted service. The attack surface is:

- The local CLI (`autosplat …`)
- The optional WebUI served at `http://127.0.0.1:8080` (`autosplat webui`)
- The optional WebUI bound to `0.0.0.0` for LAN access (`--host 0.0.0.0`)
- The optional local SuperSplat HTTP server that serves a single PLY at `/captures/{id}/scene.ply` while the viewer is open

The pipeline shells out to FFmpeg, COLMAP, Brush, npx (for `splat-transform`) and assumes those binaries are trusted system installs.

## Supported versions

Only the latest minor release (currently `v1.3.x`) receives fixes. Older releases are kept as historical references.

## Reporting a vulnerability

**Please do not file a public issue for security-sensitive reports.**

Preferred channel:

- Email: **code.jkaindl@mailbox.org** (in-repo Git identity)
- Subject line: `[security] autosplat: <short description>`

If you don't get an acknowledgement within 7 days, please open a placeholder Codeberg issue titled `Security report pending` (no details) and mention that you tried email — that flags it without disclosing the vulnerability.

Please include:

- The affected version (`autosplat version` output)
- A minimal reproduction (source video properties, CLI invocation or HTTP request, expected vs. observed behaviour)
- Any relevant `pipeline.log` lines from `<capture-dir>/pipeline.log`
- macOS version + CPU (`uname -a`)
- Your suggested severity / impact assessment

## Disclosure

This is a solo-maintained project. Realistic timeline:

- **Acknowledgement:** within 7 days
- **Triage + fix or mitigation:** best-effort within 30 days for high-severity issues
- **Public disclosure:** after a fix is released, with credit to the reporter unless they request anonymity

## Out of scope

- Issues that require pre-existing local code execution as the user (the pipeline already runs as the user and trusts the user's environment)
- Issues that require the user to deliberately invoke `autosplat webui --host 0.0.0.0` on an untrusted network (this is a documented LAN-exposure flag, not a default)
- Dependency-chain CVEs that don't affect the pipeline's actual code paths — please report those upstream first

Thanks for taking the time to report responsibly.
