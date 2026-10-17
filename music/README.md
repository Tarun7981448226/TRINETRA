# TRINETRA's music

TRINETRA makes up its own tunes when asked to play an instrument or dance — never the same twice.

- `train.py` — learns melodies (2nd-order Markov chain over pitch-in-key + note length) and chord progressions,
  separately for major and minor keys, from **POP909** (909 pop songs, MIT licence,
  https://github.com/music-x-lab/POP909-Dataset). `corpus.json.gz` is the extracted dataset (kept here so the
  model can be retrained offline: `python music/train.py train`). Output: `backend/app/static/music/model.json`.
- `fetch_samples.py` — instrument samples from the **FluidR3 GM** soundfont as rendered by
  gleitz/midi-js-soundfonts (https://github.com/gleitz/midi-js-soundfonts), licensed
  **CC BY 3.0** (https://creativecommons.org/licenses/by/3.0/). Stored in `backend/app/static/music/samples/`.
- The player is `backend/app/static/music.js`: each mood sets key (major/minor), tempo, energy and drum feel;
  each instrument accompanies itself its own way. Drums are synthesised in the browser.
