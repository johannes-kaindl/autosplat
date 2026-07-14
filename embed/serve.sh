#!/usr/bin/env bash
# Serve embed/ locally for manual smoke testing.
cd "$(dirname "$0")"
echo "→ http://localhost:8130/?src=<path-to-scene.sog>"
python3 -m http.server 8130
