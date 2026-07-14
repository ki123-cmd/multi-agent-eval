import unittest
from src.worker_pool import WorkerPool


class WorkerPoolPublicTests(unittest.TestCase):
    def test_shutdown_does_not_raise(self):
        pool = WorkerPool(worker_count=1)
        pool.submit('a')
        pool.shutdown()
        self.assertIn('a', pool.processed)


if __name__ == "__main__":
    unittest.main()
