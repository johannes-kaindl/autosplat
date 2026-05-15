---
name: Bug Report
about: Something is broken or behaving unexpectedly
labels: bug
---

## What happened?

<!-- Describe the unexpected behavior. Include the exact error message or log output. -->

## What did you expect?

<!-- What should have happened instead? -->

## Pipeline phase

<!-- Which stage failed? Check `autosplat status` output. -->
- [ ] preflight / doctor
- [ ] preprocess (ffmpeg / blur filter)
- [ ] SfM (COLMAP)
- [ ] quality gate
- [ ] training (Brush)
- [ ] export / compress
- [ ] Obsidian note generation
- [ ] SuperSplat auto-open (Phase 9)
- [ ] watch-folder daemon
- [ ] other / unknown

## Reproduction steps

```bash
# Paste the exact command(s) you ran
```

## Logs

```
# Paste relevant output from autosplat status, state.json, or terminal
```

## Environment

- macOS version:
- Apple Silicon chip (e.g. M3, M5):
- RAM:
- autosplat version (`autosplat version`):
- Python version (`python3 --version`):
- COLMAP version (`colmap --version`):
- Brush binary present (`ls ~/AutoSplat/bin/brush`):

## Additional context

<!-- Any other details — input video characteristics (duration, fps, capture style), config overrides, etc. -->
