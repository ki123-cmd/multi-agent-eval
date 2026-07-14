class HighScores {
  constructor(scores) {
    this._scores = scores;
  }

  get scores() {
    return [];
  }

  get latest() {
    return undefined;
  }

  get personalBest() {
    return undefined;
  }

  get personalTopThree() {
    return [];
  }
}

module.exports = { HighScores };
