import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "stack.containers/market-data-exporter/exporter.py"
SPEC = importlib.util.spec_from_file_location("market_data_exporter", MODULE_PATH)
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


class MarketDataExporterTest(unittest.TestCase):
    def test_default_regions_cover_dashboard_contract(self):
        regions = set(exporter.FRED_SERIES_BY_REGION) | {"australia", "crypto", "global"}
        self.assertTrue({"australia", "china", "europe", "asia", "united_states", "global", "crypto"} <= regions)

    def test_metric_compatibility_and_region_labels(self):
        lines = []
        labels = exporter.market_labels("australia", "test", "ASX", "ASX")
        exporter.emit_market_metrics(lines, labels, 101.0, 100.0, 123)
        body = "\n".join(lines)
        self.assertIn('market_data_latest_value{region="australia"', body)
        self.assertIn("market_data_daily_change_percent", body)
        self.assertIn("market_data_source_up", body)

    def test_custom_region_map(self):
        with mock.patch.dict(os.environ, {"TEST_SERIES": "oceania|ABC:Example,XYZ:Second"}):
            mapped = exporter.env_region_map("TEST_SERIES", {})
        self.assertEqual("Example", mapped["oceania"]["ABC"])
        self.assertEqual("Second", mapped["custom"]["XYZ"])

    def test_failed_source_emits_up_zero_without_aborting_render(self):
        with mock.patch.object(exporter, "fetch_text", side_effect=RuntimeError("offline")):
            body, healthy = exporter.render_metrics()
        self.assertFalse(healthy)
        self.assertIn("market_data_source_up", body)
        self.assertIn("market_data_exporter_scrape_errors_total", body)


if __name__ == "__main__":
    unittest.main()
