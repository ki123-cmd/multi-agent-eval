const assert = require('node:assert/strict');
const { HighScores } = require('../src/highScores');

const hs = new HighScores([40, 100, 70]);
const copy = hs.scores;
copy.push(999);
assert.deepEqual(hs.scores, [40, 100, 70]);
assert.deepEqual(hs.personalTopThree, [100, 70, 40]);

const short = new HighScores([8, 2]);
assert.deepEqual(short.personalTopThree, [8, 2]);
console.log('hidden tests passed');
