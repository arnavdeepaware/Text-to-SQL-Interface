import unittest

from text_to_sql.guardrails import GuardrailError, validate_readonly_sql


class GuardrailTests(unittest.TestCase):
    def test_allows_select_query(self):
        self.assertTrue(validate_readonly_sql("SELECT * FROM customers LIMIT 1;"))

    def test_blocks_mutating_query(self):
        with self.assertRaises(GuardrailError):
            validate_readonly_sql("DELETE FROM customers;")

    def test_blocks_multiple_statements(self):
        with self.assertRaises(GuardrailError):
            validate_readonly_sql("SELECT * FROM customers; SELECT * FROM orders;")

if __name__ == "__main__":
    unittest.main()
