# Task: Fix tenumerate start handling

Dataset basis: BugsInPy, project `tqdm`, bug `1`.

`tenumerate(iterable, start=N)` should behave like `enumerate(iterable, start=N)` while wrapping the iterable with a tqdm-like class. The current implementation passes `start` to the tqdm wrapper instead of to `enumerate`, so yielded indexes still start from `0`.

Edit `src/tqdm_helpers.py`. Do not change tests.

Run:

```powershell
python run_public_tests.py
python evaluate.py
```
