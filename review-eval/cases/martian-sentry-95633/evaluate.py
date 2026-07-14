import inspect
import unittest
from src.worker_pool import WorkerPool


class WorkerPoolHiddenTests(unittest.TestCase):
    def test_all_workers_exit_and_all_items_processed(self):
        pool = WorkerPool(worker_count=3)
        for value in range(10):
            pool.submit(value)
        pool.shutdown()
        self.assertEqual(sorted(pool.processed), list(range(10)))
        self.assertTrue(all(not thread.is_alive() for thread in pool._threads))

    def test_does_not_use_queue_shutdown_api(self):
        self.assertNotIn('.shutdown(', inspect.getsource(WorkerPool.shutdown))


if __name__ == "__main__":
    unittest.main()
