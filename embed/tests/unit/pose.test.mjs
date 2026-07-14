import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePose } from '../../js/params.js';

test('parsePose: valid 6-number CSV → array of floats', () => {
  assert.deepEqual(parsePose('1,2,3,4,5,6'), [1, 2, 3, 4, 5, 6]);
});

test('parsePose: tolerates whitespace and decimals/negatives', () => {
  assert.deepEqual(parsePose(' -1.5 , 2, 3.25,4,5,6'), [-1.5, 2, 3.25, 4, 5, 6]);
});

test('parsePose: wrong arity → null', () => {
  assert.equal(parsePose('1,2,3'), null);
  assert.equal(parsePose('1,2,3,4,5,6,7'), null);
});

test('parsePose: non-numeric part → null', () => {
  assert.equal(parsePose('1,2,x,4,5,6'), null);
});

test('parsePose: null/empty input → null', () => {
  assert.equal(parsePose(null), null);
  assert.equal(parsePose(''), null);
});
