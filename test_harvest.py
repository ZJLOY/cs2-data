import time
import unittest
from unittest.mock import patch

import harvest


class HarvestTest(unittest.TestCase):
    def test_distinct_sales_and_retry(self):
        data = {"sales": {"x": [[10, 5, 0.15, 1, 0]]}, "fetched": {}}
        batch = [[10, 5, 0.15, 1, 0], [10, 5, None, None, 0]]
        with patch.object(harvest.time, "sleep"), patch.object(harvest, "csfloat_sales") as get:
            get.side_effect = [TimeoutError(), (batch + batch, None, None), (batch, None, None)]
            deadline = time.time() + 30
            harvest.collect_sales(data, ["y", "x"], deadline, 1)
            self.assertNotIn("y", data["fetched"])
            for _ in range(2):
                harvest.collect_sales(data, ["y", "x"], deadline, 1)
            self.assertEqual(data["sales"]["x"], batch)
            self.assertEqual([call.args[0] for call in get.call_args_list], ["y", "x", "x"])
