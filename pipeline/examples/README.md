# Example configs

Drop-in `--config` overlays for common use cases. None of these are the *full* config — they only override the keys that matter for the use case; everything else falls back to `config/default.toml`.

```bash
uv run autosplat process import/video.mp4 --config examples/quality-run.toml
```

| File                      | Use case                                                            |
| ------------------------- | ------------------------------------------------------------------- |
| `quick-iter.toml`         | Fast iteration — 5000 Brush steps, smaller resolution_cap           |
| `quality-run.toml`        | Maximum-quality long run — 50k steps, more frames, high COLMAP      |
| `motion-blur-rescue.toml` | Fast-moving drone footage — aggressive blur_threshold lowering      |
| `watch-folder-obsidian.toml` | Watch-folder daemon with Obsidian capture-note auto-gen          |
| `compress-after.toml`     | Auto-compress to SOG + SPZ after every successful run               |

User-level config (applied to every run): write your preferred default to `~/.config/autosplat/config.toml` via `autosplat config init`.
