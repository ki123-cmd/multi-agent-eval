const assert = require('node:assert/strict');
const { HighScores } = require('../src/highScores');

const hs = new HighScores([30, 50, 20, 70]);
assert.deepEqual(hs.scores, [30, 50, 20, 70]);
assert.equal(hs.latest, 70);
assert.equal(hs.personalBest, 70);
assert.deepEqual(hs.personalTopThree, [70, 50, 30]);
console.log('public tests passed');
