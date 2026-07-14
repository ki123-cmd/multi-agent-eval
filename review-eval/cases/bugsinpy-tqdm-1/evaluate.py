import unittest
from src.tqdm_helpers import tenumerate


class TEnumerateHiddenTests(unittest.TestCase):
    def test_start_not_forwarded_to_tqdm_class(self):
        seen_kwargs = {}

        def wrapper(iterable, **kwargs):
            seen_kwargs.update(kwargs)
            return iterable

        result = list(tenumerate([10, 20], start=3, tqdm_class=wrapper))
        self.assertEqual(result, [(3, 10), (4, 20)])
        self.assertNotIn("start", seen_kwargs)
        self.assertEqual(seen_kwargs.get("total"), 2)


if __name__ == "__main__":
    unittest.main()
