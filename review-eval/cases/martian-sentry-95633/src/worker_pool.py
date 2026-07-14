import queue
import threading

STOP = object()


class WorkerPool:
    def __init__(self, worker_count=2):
        self.worker_count = worker_count
        self.queue = queue.Queue()
        self.processed = []
        self._threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(worker_count)]
        for thread in self._threads:
            thread.start()

    def submit(self, item):
        self.queue.put(item)

    def _worker(self):
        while True:
            item = self.queue.get()
            try:
                if item is STOP:
                    return
                self.processed.append(item)
            finally:
                self.queue.task_done()

    def shutdown(self, timeout=1.0):
        self.queue.shutdown(immediate=False)
        for thread in self._threads:
            thread.join(timeout)
