from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import importlib
import unittest
from unittest.mock import patch

import pandas as pd

download = importlib.import_module("etl.01_download_data")


class DengueSplitTest(unittest.TestCase):
    def test_duplicate_period_is_split(self):
        def fake_get_infodengue(**kwargs):
            start = date.fromisoformat(kwargs["start_date"])
            row = {
                "id": start.isoformat(),
                "municipio_geocodigo": 1,
                "SE": int(start.strftime("%Y%m%d")),
                "Localidade_id": 0,
            }
            if (
                kwargs["start_date"] == "2020-01-01"
                and kwargs["end_date"] == "2020-01-14"
            ):
                return pd.DataFrame([row, row.copy()])
            return pd.DataFrame([row])

        with TemporaryDirectory() as directory, patch.object(
            download, "RAW_DIR", Path(directory)
        ), patch.object(
            download, "get_infodengue", side_effect=fake_get_infodengue
        ):
            result = download.fetch_dengue_period(
                "unused",
                "AL",
                2020,
                date(2020, 1, 1),
                date(2020, 1, 14),
            )
            self.assertEqual(len(result), 2)
            self.assertFalse(download.has_duplicate_dengue_rows(result))

    def test_failed_period_is_split(self):
        def fake_get_infodengue(**kwargs):
            start = date.fromisoformat(kwargs["start_date"])
            end = date.fromisoformat(kwargs["end_date"])
            if (end - start).days > 7:
                raise RuntimeError("temporary API failure")
            return pd.DataFrame(
                [{
                    "id": start.isoformat(),
                    "municipio_geocodigo": 1,
                    "SE": int(start.strftime("%Y%m%d")),
                    "Localidade_id": 0,
                }]
            )

        with TemporaryDirectory() as directory, patch.object(
            download, "RAW_DIR", Path(directory)
        ), patch.object(
            download, "get_infodengue", side_effect=fake_get_infodengue
        ):
            result = download.fetch_dengue_period(
                "unused",
                "AL",
                2020,
                date(2020, 1, 1),
                date(2020, 1, 14),
            )
            self.assertEqual(len(result), 2)
            self.assertFalse(download.has_duplicate_dengue_rows(result))


if __name__ == "__main__":
    unittest.main()
