import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.providers.discovery_base import DiscoveryProvider, DiscoveryResult  # noqa: E402
from app.providers import discovery_registry  # noqa: E402


class _FakeProvider(DiscoveryProvider):
    label = "Fake 源"

    def __init__(self, name="fake", results=None, error=False):
        self.name = name
        self._results = results or []
        self._error = error

    def search(self, keyword, **kwargs):
        if self._error:
            raise RuntimeError("boom")
        return self._results


class DiscoveryRegistryTest(unittest.TestCase):
    def setUp(self):
        self._original = dict(discovery_registry._discovery_providers)

    def tearDown(self):
        discovery_registry._discovery_providers.clear()
        discovery_registry._discovery_providers.update(self._original)

    def test_register_list_get(self):
        provider = _FakeProvider()
        discovery_registry.register_discovery(provider)
        self.assertIs(discovery_registry.get_discovery_provider("fake"), provider)
        self.assertIn(provider, discovery_registry.list_discovery_providers())

    def test_register_requires_name(self):
        with self.assertRaises(ValueError):
            discovery_registry.register_discovery(_FakeProvider(name=""))

    def test_duplicate_registration_replaces(self):
        first = _FakeProvider()
        second = _FakeProvider()
        discovery_registry.register_discovery(first)
        discovery_registry.register_discovery(second)
        self.assertIs(discovery_registry.get_discovery_provider("fake"), second)

    def test_search_all_aggregates_and_isolates_errors(self):
        discovery_registry._discovery_providers.clear()
        discovery_registry.register_discovery(
            _FakeProvider(
                name="fake",
                results=[DiscoveryResult(title="A", link_url="https://a", link_type="magnet")],
            )
        )
        discovery_registry.register_discovery(_FakeProvider(name="fake_error", error=True))
        payload = discovery_registry.search_all("黑客帝国")
        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["results"][0].title, "A")
        self.assertEqual(len(payload["errors"]), 1)
        self.assertEqual(payload["errors"][0]["provider"], "fake_error")

    def test_search_all_respects_provider_filter(self):
        discovery_registry._discovery_providers.clear()
        discovery_registry.register_discovery(
            _FakeProvider(
                name="fake",
                results=[DiscoveryResult(title="A", link_url="https://a", link_type="magnet")],
            )
        )
        discovery_registry.register_discovery(_FakeProvider(name="fake_error", error=True))
        payload = discovery_registry.search_all("黑客帝国", provider_filter=["fake"])
        self.assertEqual(payload["stats"]["total"], 1)
        filtered = discovery_registry.search_all("黑客帝国", provider_filter=["missing"])
        self.assertEqual(filtered["stats"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
