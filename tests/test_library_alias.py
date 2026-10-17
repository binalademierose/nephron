"""The model loaders must accept xgboost installed as either the full 'xgboost' wheel or the smaller CPU-only
'xgboost-cpu' wheel (same import, same version line) - otherwise a perfectly good xgboost-cpu install, which is
what a size-limited host such as Vercel needs, would be reported as 'not installed'. See services/model_service.py.
"""
import importlib.metadata
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.model_service import _installed_version


class LibraryAliasTests(unittest.TestCase):
    def test_plain_xgboost_is_found(self):
        self._with_installed({"xgboost": "3.1.3"}, lambda: self.assertEqual(_installed_version("xgboost"), "3.1.3"))

    def test_cpu_only_xgboost_is_found_under_its_own_name(self):
        # Only xgboost-cpu is installed (the full 'xgboost' distribution is absent): it must still be found.
        self._with_installed({"xgboost-cpu": "3.1.3"}, lambda: self.assertEqual(_installed_version("xgboost"), "3.1.3"))

    def test_neither_installed_returns_none(self):
        self._with_installed({}, lambda: self.assertIsNone(_installed_version("xgboost")))

    def test_a_normal_distribution_is_unaffected(self):
        self._with_installed({"scikit-learn": "1.8.0"}, lambda: self.assertEqual(_installed_version("scikit-learn"), "1.8.0"))

    def _with_installed(self, available, body):
        """Run body() with importlib.metadata.version answering only for the names in `available`."""
        real = importlib.metadata.version

        def fake(name):
            if name in available:
                return available[name]
            raise importlib.metadata.PackageNotFoundError(name)

        importlib.metadata.version = fake
        try:
            body()
        finally:
            importlib.metadata.version = real


if __name__ == "__main__":
    unittest.main()
