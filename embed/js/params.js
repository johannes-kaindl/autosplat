// Pure URL-parameter parsing for the embed page — unit-testable in node.
export function parseParams(search) {
  const q = new URLSearchParams(search);
  const src = (q.get('src') || '').trim() || null;
  const poster = (q.get('poster') || '').trim() || null;
  const autoplay = q.get('autoplay') === '1';
  const filename = src
    ? (src.split('?')[0].split('#')[0].split('/').pop() || 'scene.sog')
    : null;
  return { src, poster, autoplay, filename };
}

// "max_strasse.sog" → "max strasse" — a quiet human label for the gate card.
export function sceneLabel(filename) {
  if (!filename) return '';
  return filename.replace(/\.(sog|ply)$/i, '').replace(/[-_]+/g, ' ');
}
