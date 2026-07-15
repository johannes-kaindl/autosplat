import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePose, serializePose } from '../../js/params.js';

test('parsePose: valid 7-number CSV → array of floats', () => {
  assert.deepEqual(parsePose('1,2,3,4,5,6,7'), [1, 2, 3, 4, 5, 6, 7]);
});

test('parsePose: tolerates whitespace and decimals/negatives', () => {
  assert.deepEqual(parsePose(' -1.5 , 2, 3.25,4,5,6,7'), [-1.5, 2, 3.25, 4, 5, 6, 7]);
});

test('parsePose: wrong arity → null', () => {
  assert.equal(parsePose('1,2,3'), null);
  assert.equal(parsePose('1,2,3,4,5,6'), null);
  assert.equal(parsePose('1,2,3,4,5,6,7,8'), null);
});

test('parsePose: non-numeric part → null', () => {
  assert.equal(parsePose('1,2,x,4,5,6,7'), null);
});

test('parsePose: null/empty input → null', () => {
  assert.equal(parsePose(null), null);
  assert.equal(parsePose(''), null);
});

test('serializePose: formats 7 numbers to 3 decimal places, comma-joined', () => {
  assert.equal(
    serializePose([1, -2.5, 3, 4, 5, 6, 90]),
    '1.000,-2.500,3.000,4.000,5.000,6.000,90.000');
});

test('serializePose / parsePose round-trip', () => {
  const original = [-2.078, -1.129, 3.226, 0, 0, 0, 42.5];
  const roundTripped = parsePose(serializePose(original));
  original.forEach((n, i) => assert.ok(Math.abs(roundTripped[i] - n) < 0.001));
});
