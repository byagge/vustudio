#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import unittest

from vu_testdata import MOCKUP_CATEGORIES, make_valid, new_rng, parse_identity


class TestMockupCategories(unittest.TestCase):
    def test_product_generate_only_bb1m(self):
        ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
        rng = new_rng(21)
        allowed = set(MOCKUP_CATEGORIES)
        for _ in range(80):
            rec = make_valid(
                rng,
                identity=ident,
                valid_now=True,
                allowed_categories=MOCKUP_CATEGORIES,
            )
            self.assertTrue(set(rec.categories) <= allowed, rec.categories)
            self.assertEqual(set(rec.back_table), set(rec.categories))
            self.assertIn("B", rec.categories)
            self.assertIn("B1", rec.categories)
            self.assertIn("M", rec.categories)

    def test_unrestricted_can_include_c(self):
        ident = parse_identity("ЩЕРБАКОВ ДМИТРИЙ ВАЛЕНТИНОВИЧ 14.03.1988")
        rng = new_rng(3)
        seen = set()
        for _ in range(200):
            rec = make_valid(rng, identity=ident)
            seen.update(rec.categories)
        self.assertTrue({"C", "A", "D"} & seen, f"expected extra cats in QA generator, got {seen}")


if __name__ == "__main__":
    unittest.main()
