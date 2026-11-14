"""Synthetic ranking tests, not evidence of live ranking quality."""
import unittest
from lesser_tokenzz.discovery_audit import discovery_audit
from lesser_tokenzz.search_provider import SearchHit, SearchResponse
from lesser_tokenzz.telem_provider import TelemProvider


class DiscoveryTests(unittest.TestCase):
    def test_duplicates_count_once_and_unreviewed_sources_rejected(self):
        def hit(url, provider):
            return SearchHit('', url, '', '', provider, {})
        result = discovery_audit(SearchResponse([
            hit('https://official.example/list', 'one'),
            hit('https://official.example/list', 'one'),
            hit('https://untrusted.example', 'two'),
            hit('https://official.example/list', 'two'),
        ], 0, 'mock', usage={'response': {'routing': [{'providers': ['one', 'two']}]}}), ['https://official.example/list'])
        self.assertEqual(len(result['selected_sources']), 1)
        row = result['selected_sources'][0]
        self.assertAlmostEqual(row['rrf_score'], 1/61 + 1/62, places=7)
        self.assertEqual(len(row['providers']), 2)
        self.assertEqual(result['rejected_result_count'], 1)

    def test_routing_is_explicit_and_bounded(self):
        def transport(path, payload):
            self.assertEqual(payload['search']['auto_routing'], 'accuracy')
            self.assertEqual(payload['search']['providers']['include'], ['brave', 'tavily'])
            return {'preprocessor_runs': []}
        TelemProvider(search_providers=['brave', 'tavily'], fetch_providers=['tavily'],
                      auto_routing='accuracy', transport=transport).search('public query')

    def test_invalid_routing_mode(self):
        with self.assertRaises(ValueError):
            TelemProvider(search_providers=['brave'], fetch_providers=['tavily'], auto_routing='invented')
