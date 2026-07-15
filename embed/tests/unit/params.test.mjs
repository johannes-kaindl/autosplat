import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseParams, sceneLabel } from '../../js/params.js';

test('parseParams: src + filename derived', () => {
  const p = parseParams('?src=c/scene.sog');
  assert.equal(p.src, 'c/scene.sog');
  assert.equal(p.filename, 'scene.sog');
  assert.equal(p.poster, null);
  assert.equal(p.autoplay, false);
});

test('parseParams: empty search → no src', () => {
  const p = parseParams('');
  assert.equal(p.src, null);
  assert.equal(p.filename, null);
});

test('parseParams: poster + autoplay flags', () => {
  const p = parseParams('?src=a/b/haus.ply&poster=p.jpg&autoplay=1');
  assert.equal(p.poster, 'p.jpg');
  assert.equal(p.autoplay, true);
  assert.equal(p.filename, 'haus.ply');
});

test('parseParams: autoplay only for exact "1"', () => {
  assert.equal(parseParams('?src=x.sog&autoplay=yes').autoplay, false);
});

test('parseParams: filename strips query and hash', () => {
  const p = parseParams('?src=' + encodeURIComponent('c/scene.sog?v=2#frag'));
  assert.equal(p.filename, 'scene.sog');
});

test('sceneLabel: strips extension, prettifies separators', () => {
  assert.equal(sceneLabel('max_strasse.sog'), 'max strasse');
  assert.equal(sceneLabel('wasser-turm.ply'), 'wasser turm');
  assert.equal(sceneLabel(null), '');
});

test('parseParams: orbit defaults true, "0" disables it, anything else stays true', () => {
  assert.equal(parseParams('?src=x.sog').orbit, true);
  assert.equal(parseParams('?src=x.sog&orbit=0').orbit, false);
  assert.equal(parseParams('?src=x.sog&orbit=yes').orbit, true);
});

test('parseParams: authoring only for exact "1"', () => {
  assert.equal(parseParams('?src=x.sog').authoring, false);
  assert.equal(parseParams('?src=x.sog&authoring=1').authoring, true);
  assert.equal(parseParams('?src=x.sog&authoring=true').authoring, false);
});

test('parseParams: valid pose is parsed through, invalid pose is null', () => {
  const p = parseParams('?src=x.sog&pose=1,2,3,4,5,6,7');
  assert.deepEqual(p.pose, [1, 2, 3, 4, 5, 6, 7]);
  assert.equal(parseParams('?src=x.sog&pose=1,2,3').pose, null);
  assert.equal(parseParams('?src=x.sog&pose=1,2,3,4,5,6').pose, null);
  assert.equal(parseParams('?src=x.sog').pose, null);
});
