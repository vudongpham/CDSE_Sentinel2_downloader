import argparse
import os
import unittest
from pathlib import Path
from unittest import mock

from cdse import search
from cdse.search import (argparseCondition, build_query, convert_aoi_to_s2idlist, filter_results,
                         parse_tile_ids, read_list_id, search_by_list, search_force_logs)

ROOT = Path(__file__).parents[1]
DIR_TESTDATA = ROOT / 'test_data'
DIR_FORCELOGS = DIR_TESTDATA / 'force_logs'
ONLINE = os.environ.get('CDSE_ONLINE_TESTS') == '1'


class ArgumentTestCase(unittest.TestCase):
    def setUp(self):
        self.check = argparseCondition()

    def test_daterange(self):
        self.assertEqual(self.check.dateRangeInput('20240101,20240131'), ('2024-01-01', '2024-01-31'))
        for bad in ['20240101', '20240132,20240201', '20240201,20240101']:
            with self.assertRaises(argparse.ArgumentTypeError):
                self.check.dateRangeInput(bad)

    def test_cloudcover(self):
        self.assertEqual(self.check.cloudCoverInput('0,75'), (0, 75))
        for bad in ['0', '-1,50', '0,101', '80,20', 'a,b']:
            with self.assertRaises(argparse.ArgumentTypeError):
                self.check.cloudCoverInput(bad)

    def test_months_and_satellite(self):
        self.assertEqual(self.check.monthsInput('8,6,7'), [6, 7, 8])
        self.assertEqual(self.check.satelliteInput('a,S2B'), ['S2A', 'S2B'])
        with self.assertRaises(argparse.ArgumentTypeError):
            self.check.monthsInput('13')
        with self.assertRaises(argparse.ArgumentTypeError):
            self.check.satelliteInput('S2X')


class AoiTestCase(unittest.TestCase):
    def test_vector_to_tiles(self):
        tiles = convert_aoi_to_s2idlist(DIR_TESTDATA / 'berlin_boundary.gpkg')
        self.assertEqual(tiles, ['32UQD', '33UUT', '33UUU', '33UVT', '33UVU'])

    def test_vector_with_prfid_column(self):
        # this file has a PRFID column itself, which used to break gpd.overlay
        self.assertGreater(len(convert_aoi_to_s2idlist(DIR_TESTDATA / 'test_bound1.gpkg')), 0)

    def test_txt_list(self):
        ids = read_list_id(DIR_TESTDATA / 'list_test1.txt')
        self.assertTrue(ids)
        self.assertTrue(all(len(i) == 5 for i in ids))
        self.assertEqual(read_list_id(DIR_TESTDATA / 'list_test4.txt'), ['31UGT'])  # no trailing newline

    def test_parse_tile_ids(self):
        self.assertEqual(parse_tile_ids('T32UQD, 33uuu,32UQD'), ['32UQD', '33UUU'])
        self.assertIsNone(parse_tile_ids('not/a/file.gpkg'))


class QueryTestCase(unittest.TestCase):
    def test_build_query_end_date_inclusive(self):
        q = build_query('32UNC', '2024-01-01', '2024-01-31', 0, 75, 'S2MSI2A')
        self.assertIn("ContentDate/Start ge 2024-01-01T00:00:00.000Z", q)
        self.assertIn("ContentDate/Start lt 2024-02-01T00:00:00.000Z", q)
        self.assertIn("Value eq 'S2MSI2A'", q)
        self.assertIn("Value eq '32UNC'", q)
        self.assertIn("Value le 75.00", q)
        self.assertNotIn("Value ge 0.00", q)  # no-op filter is skipped

    def test_search_by_list_paginates_and_dedups(self):
        pages = {
            'A1': {'value': [{'Id': '1', 'Name': 'S2A_x', 'ContentDate': {'Start': '2024-01-02'}}],
                   '@odata.nextLink': 'A2'},
            'A2': {'value': [{'Id': '2', 'Name': 'S2B_y', 'ContentDate': {'Start': '2024-01-01'}}]},
            'B1': {'value': [{'Id': '1', 'Name': 'S2A_x', 'ContentDate': {'Start': '2024-01-02'}}]},
        }

        class Resp:
            def __init__(self, d): self.d = d
            def raise_for_status(self): pass
            def json(self): return self.d

        def fake_get(url, timeout=None):
            return Resp(pages[url])

        with mock.patch.object(search, 'build_query', side_effect=lambda t, *a, **k: f'{t}1'), \
             mock.patch('requests.Session.get', side_effect=fake_get):
            res = search_by_list('2024-01-01', '2024-01-31', 0, 100, ['A', 'B'], verbose=False)
        self.assertEqual([r['Id'] for r in res], ['2', '1'])  # deduplicated + sorted by date

    def test_filter_results(self):
        rs = [{'Name': 'S2A_1', 'ContentDate': {'Start': '2024-06-01T10:00:00Z'}},
              {'Name': 'S2B_2', 'ContentDate': {'Start': '2024-07-01T10:00:00Z'}},
              {'Name': 'S2C_3', 'ContentDate': {'Start': '2024-12-01T10:00:00Z'}, 'Online': False}]
        self.assertEqual(len(filter_results(rs, ['S2A', 'S2C'])), 2)
        self.assertEqual(len(filter_results(rs, months=[6, 7])), 2)
        self.assertEqual(len(filter_results(rs, online_only=True)), 2)


class FORCETestCase(unittest.TestCase):
    def test_search_force_logs(self):
        examples = [
            (8, {}),  # all logs, recursively
            (5, {'recursive': False}),  # all logs, non-recursively
            (5, {'rx': r'^S2[ABCD]_MSIL1C.*\.log$'}),  # only S2 logs, recursively
            (3, {'rx': r'^S2[ABCD]_MSIL1C.*\.log$', 'recursive': False}),  # only S2 logs, non-recursively
            (3, {'rx': r'^L(T04|T05|E07|C08|C09).*\.log$'}),  # only Landsat logs, recursively
            (2, {'rx': r'^L(T04|T05|E07|C08|C09).*\.log$', 'recursive': False}),  # Landsat, non-recursively
        ]
        for (n_expected, kwargs) in examples:
            n = len(list(search_force_logs(DIR_FORCELOGS, **kwargs)))
            self.assertEqual(n_expected, n, msg=f'Expected {n_expected} logfiles, got {n} with kwargs "{kwargs}"')


@unittest.skipUnless(ONLINE, 'set CDSE_ONLINE_TESTS=1 to query the real CDSE catalogue')
class OnlineTestCase(unittest.TestCase):
    def test_search_by_list(self):
        data_return = search_by_list('2024-01-01', '2024-01-23', 0, 100, ['32UNC'])
        self.assertTrue(len(data_return) != 0)


if __name__ == '__main__':
    unittest.main()
