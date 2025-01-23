import os
import unittest
from pathlib import Path

from search import search_by_list, search_by_aoi

ROOT = Path(__file__).parents[1]
DIR_TESTDATA = ROOT / 'test_data'


class FORCETestCase(unittest.TestCase):

    def create_tmp_dir(self) -> Path:
        """
        Create a temporary directory for the calling test method.
        """
        root = Path(__file__).parents[1] / 'tmp'
        path = root / self.__class__.__name__ / self._testMethodName
        os.makedirs(path, exist_ok=True)
        return path

    def test_search_by_aoi(self):
        # rectangle around berlin
        tmp_dir = self.create_tmp_dir()

        path_json = tmp_dir / 'results_search_by_wkt.json'
        aoi_wkt = 'POLYGON ((13.11590671451530987 52.64717493209391108, 13.11590671451530987 52.32335479958383218, 13.82003839127742317 52.32335479958383218, 13.82003839127742317 52.64717493209391108, 13.11590671451530987 52.64717493209391108))'
        data_return = search_by_aoi('2024-01-01', '2024-01-31', 0, 100, aoi_wkt)

        self.assertTrue(len(data_return) > 0,
                        msg='Failed to query by WKT')

        path_json = tmp_dir / 'results_search_by_gpkg.json'
        path_gpkg = DIR_TESTDATA / 'test_bound1.gpkg'
        data_return = search_by_aoi('2024-01-01', '2024-01-31', 0, 100, aoi_wkt)

        self.assertTrue(len(data_return) > 0,
                        msg=f'Failed to query by {path_gpkg}')

    def test_search_by_list(self):

        list_ids = ['32UNC']
        data_return = search_by_list('2024-01-01', '2024-01-23',0, 100, list_ids)
        self.assertTrue(len(data_return) != 0)

    def test_search_exclude_force(self):

        list_ids = ['32UNC']


if __name__ == '__main__':
    unittest.main()
