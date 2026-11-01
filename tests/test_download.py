import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from cdse import download
from cdse.download import (DownloadError, TokenManager, download_all, download_product,
                           get_secret_from_text, is_downloaded, load_products)

PAYLOAD = os.urandom(3 * 1024 * 1024 + 17)


class FakeCDSE(BaseHTTPRequestHandler):
    truncate = False
    fail_first = 0
    calls = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.dumps({'access_token': 'tok', 'expires_in': 600,
                           'refresh_token': 'ref', 'refresh_expires_in': 3600}).encode()
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        cls = type(self)
        if self.path.startswith('/redirect/'):
            self.send_response(307)
            self.send_header('Location', self.path.replace('/redirect/', '/data/'))
            self.end_headers()
            return
        if self.headers.get('Authorization') != 'Bearer tok':
            self.send_response(401)
            self.end_headers()
            return
        cls.calls += 1
        if cls.calls <= cls.fail_first:
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD[:1000] if cls.truncate else PAYLOAD)


class DownloadTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), FakeCDSE)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeCDSE.truncate, FakeCDSE.fail_first, FakeCDSE.calls = False, 0, 0
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.patches = [
            mock.patch.object(download, 'TOKEN_URL', f'{self.base}/token'),
            mock.patch.object(download, 'DOWNLOAD_URL', self.base + '/redirect/{}'),
            mock.patch('time.sleep'),
        ]
        for p in self.patches:
            p.start()
        self.tm = TokenManager('u', 'p')
        self.session = download.make_session(retries=0)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def product(self, n=1, md5=None):
        p = {'Id': f'id-{n}', 'Name': f'S2A_MSIL1C_TEST{n}.SAFE', 'ContentLength': len(PAYLOAD)}
        if md5:
            p['Checksum'] = [{'Algorithm': 'MD5', 'Value': md5}]
        return p

    def test_download_follows_redirect_and_verifies(self):
        md5 = hashlib.md5(PAYLOAD).hexdigest()
        path = download_product(self.session, self.tm, self.product(md5=md5), self.dir, verify_checksum=True)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), PAYLOAD)
        self.assertEqual(os.listdir(self.dir), ['S2A_MSIL1C_TEST1.zip'])

    def test_bad_checksum_leaves_no_file(self):
        with self.assertRaises(DownloadError):
            download_product(self.session, self.tm, self.product(md5='0' * 32), self.dir,
                             retries=2, verify_checksum=True)
        self.assertEqual(os.listdir(self.dir), [])

    def test_truncated_download_is_retried_then_fails_cleanly(self):
        FakeCDSE.truncate = True
        with self.assertRaises(DownloadError):
            download_product(self.session, self.tm, self.product(), self.dir, retries=2)
        self.assertEqual(os.listdir(self.dir), [])

    def test_retry_after_error(self):
        FakeCDSE.fail_first = 1
        download_product(self.session, self.tm, self.product(), self.dir, retries=2)
        self.assertTrue(is_downloaded('S2A_MSIL1C_TEST1', self.dir))

    def test_download_all_parallel(self):
        failed = download_all([self.product(i) for i in range(5)], self.dir, self.tm, workers=3)
        self.assertEqual(failed, [])
        self.assertEqual(len(os.listdir(self.dir)), 5)

    def test_part_file_not_counted_as_downloaded(self):
        open(os.path.join(self.dir, 'S2A_X.zip.part'), 'w').close()
        self.assertFalse(is_downloaded('S2A_X', self.dir))
        open(os.path.join(self.dir, 'S2A_X.zip'), 'w').close()
        self.assertTrue(is_downloaded('S2A_X', self.dir))

    def test_token_refresh_on_expiry(self):
        self.assertEqual(self.tm.get(), 'tok')
        self.tm._expires = 0
        with mock.patch.object(download, '_request_token', wraps=download._request_token) as rt:
            self.tm.get()
            self.assertEqual(rt.call_args[0][0]['grant_type'], 'refresh_token')


class InputTestCase(unittest.TestCase):
    def test_secret_with_comma_in_password(self):
        self.assertEqual(get_secret_from_text('me@x.org,pa,ss'), ('me@x.org', 'pa,ss'))

    def test_load_products(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump([], f)
        try:
            with self.assertRaises(TypeError):
                load_products(f.name)
        finally:
            os.remove(f.name)


if __name__ == '__main__':
    unittest.main()
