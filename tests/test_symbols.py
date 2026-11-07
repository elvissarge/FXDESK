import unittest

from fxdesk.symbols import (
    base_symbol,
    pip_value_per_lot,
    price_to_pips,
    spec_for,
)


class SymbolTests(unittest.TestCase):
    def test_broker_suffix_is_ignored(self):
        self.assertEqual(base_symbol("EURUSD.a"), "EURUSD")
        self.assertEqual(base_symbol("XAUUSDm"), "XAUUSD")
        self.assertEqual(spec_for("EURUSD.a").base, "EUR")

    def test_jpy_pair_metadata(self):
        spec = spec_for("USDJPY")
        self.assertEqual(spec.digits, 3)
        self.assertAlmostEqual(spec.pip_size, 0.01)

    def test_pip_values(self):
        eurusd = spec_for("EURUSD")
        self.assertAlmostEqual(pip_value_per_lot(eurusd, 1.10, "USD"), 10.0)

        usdjpy = spec_for("USDJPY")
        self.assertAlmostEqual(
            pip_value_per_lot(usdjpy, 150.0, "USD"), 100000 * 0.01 / 150.0
        )

        gold = spec_for("XAUUSD")
        self.assertAlmostEqual(pip_value_per_lot(gold, 2000.0, "USD"), 1.0)

    def test_price_to_pips(self):
        spec = spec_for("EURUSD")
        self.assertAlmostEqual(price_to_pips(spec, 0.0025), 25.0)


if __name__ == "__main__":
    unittest.main()
