# Task: Stop workers without Queue.shutdown

Dataset basis: Martian Code Review Benchmark, Sentry PR 95633 golden review comment.

Bug: `WorkerPool.shutdown()` calls `self.queue.shutdown(immediate=False)`, but standard `queue.Queue` does not provide that method. Stop the pool by enqueueing one sentinel per worker, wait for queued work to finish, and join worker threads.

Edit `src/worker_pool.py`. Do not change tests.

Run:

```powershell
python run_public_tests.py
python evaluate.py
```
