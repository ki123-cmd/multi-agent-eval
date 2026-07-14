import unittest
from src.tqdm_helpers import tenumerate


class TEnumeratePublicTests(unittest.TestCase):
    def test_start_offsets_indexes(self):
        self.assertEqual(list(tenumerate(["a", "b"], start=5)), [(5, "a"), (6, "b")])


if __name__ == "__main__":
    unittest.main()
