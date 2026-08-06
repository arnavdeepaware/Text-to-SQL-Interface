import unittest

from text_to_sql.generator import generate_sql


class GeneratorTests(unittest.TestCase):
    def test_revenue_by_product_prefers_product_grouping(self):
        sql = generate_sql("Show revenue by product", {}).sql
        self.assertIn("GROUP BY p.id", sql)
        self.assertIn("p.name AS product", sql)

    def test_revenue_by_region_prefers_region_grouping(self):
        sql = generate_sql("Show revenue by region", {}).sql
        self.assertIn("GROUP BY c.region", sql)
        self.assertIn("c.region", sql)


if __name__ == "__main__":
    unittest.main()
