"""A sparse-incidence boundary example for the support-two theorem."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cascades import Graph, rebuild, update


class SupportBoundaryTests(unittest.TestCase):
    def test_four_parallel_labels_create_support_three(self):
        graph = Graph(2, 4, (1,), tuple((0, 1, a) for a in range(4)))
        old, _ = rebuild((graph,), (2, 2, 2, 2))
        new, _ = rebuild((graph,), (1, 2, 2, 2))
        self.assertEqual(old[0].h, (2, 0))
        self.assertEqual(new[0].h, (1, 0))
        self.assertEqual(old[0].allocated, (2, 2, 2, 2))
        self.assertEqual(new[0].allocated, (1, 1, 1, 1))
        old_residual = tuple(x - y for x, y in zip(old[0].offered, old[0].allocated))
        new_residual = tuple(x - y for x, y in zip(new[0].offered, new[0].allocated))
        self.assertEqual(old_residual, (0, 0, 0, 0))
        self.assertEqual(new_residual, (0, 1, 1, 1))
        self.assertEqual(sum(a != b for a, b in zip(old_residual, new_residual)), 3)
        self.assertEqual([sum(a in g.support for g in (graph,)) for a in range(4)], [1] * 4)

    def test_unbounded_support_is_compatible_with_incidence_one(self):
        for labels in range(3, 10):
            with self.subTest(labels=labels):
                graph = Graph(2, labels, (1,), tuple((0, 1, a) for a in range(labels)))
                tables, _ = rebuild((graph,), (1,) + (2,) * (labels - 1))
                residual = tuple(x - y for x, y in zip(tables[0].offered, tables[0].allocated))
                self.assertEqual(residual, (0,) + (1,) * (labels - 1))

    def test_exact_update_still_matches_rebuilding_outside_bound(self):
        graph = Graph(2, 4, (1,), tuple((0, 1, a) for a in range(4)))
        old, _ = rebuild((graph,), (2, 2, 2, 2))
        expected, _ = rebuild((graph,), (1, 2, 2, 2))
        repaired, _ = update((graph,), old, (1, 2, 2, 2))
        self.assertEqual(repaired, expected)


if __name__ == '__main__':
    unittest.main()
