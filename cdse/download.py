"""Download Sentinel-2 products listed in a cdse-search JSON file from CDSE."""
import argparse
import glob
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests

from cdse._http import make_session

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DOWNLOAD_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products({})/$value"
MAX_WORKERS = 4         # CDSE allows at most 4 concurrent downloads per user
CHUNK_SIZE = 1024 * 1024
PART_SUFFIX = ".part"


class DownloadError(Exception):
    pass


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------
def load_products(jsonFile) -> list:
    """Load the product list written by cdse-search."""
    with open(jsonFile, 'r') as file:
        try:
            data = json.load(file)
        except json.JSONDecodeError as e:
            raise TypeError(f"{jsonFile} is not a valid JSON file: {e}")
    if isinstance(data, dict):  # raw OData response
        data = data.get('value', [])
    if not isinstance(data, list) or not data or not all('Id' in d and 'Name' in d for d in data):
        raise TypeError("JSON file is empty or not in the correct format. Process ends!")
    return data


def product_basename(product: dict) -> str:
    return product['Name'].split('.')[0]


def read_json_results(jsonFile):
    """Backwards compatible helper returning (ids, names)."""
    data = load_products(jsonFile)
    return [d['Id'] for d in data], [product_basename(d) for d in data]


def is_downloaded(image_name, downloadDir) -> bool:
    """A product counts as downloaded if '<name>.zip' / '<name>.SAFE' (or any '<name>.*'
    that is not an unfinished '.part' file) exists in downloadDir."""
    pattern = os.path.join(glob.escape(downloadDir), f"{glob.escape(image_name)}.*")
    return any(not f.endswith(PART_SUFFIX) for f in glob.glob(pattern))


def filtering_dir(image_id, image_name, downloadDir):
    """Backwards compatible helper: drop products already present in downloadDir."""
    keep = [(i, n) for i, n in zip(image_id, image_name) if not is_downloaded(n, downloadDir)]
    return [k[0] for k in keep], [k[1] for k in keep]


# ---------------------------------------------------------------------------
# Credentials / authentication
# ---------------------------------------------------------------------------
def get_secret_from_file(file_dir):
    with open(file_dir, 'r') as file:
        data = [line.strip() for line in file if line.strip()]
    if len(data) < 2:
        sys.exit(f'{file_dir} does not have the right format, please check again!\n'
                 'First line:<username>\nSecond line:<password>')
    return data[0], data[1]


def get_secret_from_text(string_in):
    if ',' not in string_in:
        sys.exit('Secret must be a file or a "<username>,<password>" string')
    user_name, password = string_in.split(',', 1)  # passwords may contain commas
    return user_name, password


def get_credentials(secret=None):
    """Credentials from a secret file, a 'user,password' string, or the
    CDSE_USERNAME / CDSE_PASSWORD environment variables."""
    if secret:
        if os.path.isfile(secret):
            return get_secret_from_file(secret)
        return get_secret_from_text(secret)
    user, pwd = os.environ.get('CDSE_USERNAME'), os.environ.get('CDSE_PASSWORD')
    if user and pwd:
        return user, pwd
    sys.exit('No credentials given: pass a secret file / "<username>,<password>" '
             'or set CDSE_USERNAME and CDSE_PASSWORD')


def _request_token(data, retries=3):
    for attempt in range(retries):
        try:
            r = requests.post(TOKEN_URL, data=data, timeout=60)
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            continue
        if r.status_code >= 500 and attempt < retries - 1:
            time.sleep(2 ** attempt)
            continue
        if r.status_code != 200:
            raise DownloadError(f"Token request failed: HTTP {r.status_code} {r.text[:200]}")
        return r.json()


def get_token(username, password):
    return _request_token({
        "client_id": "cdse-public",
        "username": username,
        "password": password,
        "grant_type": "password",
    })["access_token"]


class TokenManager:
    """Thread-safe access token cache that refreshes before expiry
    (using the refresh token when possible)."""

    MARGIN = 60  # seconds before expiry at which the token is renewed

    def __init__(self, username, password):
        self.username = username
        self.password = password
        self._lock = threading.Lock()
        self._token = None
        self._refresh = None
        self._expires = 0.0
        self._refresh_expires = 0.0

    def _store(self, payload):
        now = time.time()
        self._token = payload["access_token"]
        self._expires = now + payload.get("expires_in", 600)
        self._refresh = payload.get("refresh_token")
        self._refresh_expires = now + payload.get("refresh_expires_in", 3600)

    def _renew(self):
        now = time.time()
        if self._refresh and now < self._refresh_expires - self.MARGIN:
            try:
                self._store(_request_token({
                    "client_id": "cdse-public",
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh,
                }))
                return
            except DownloadError:
                pass  # fall back to password login
        self._store(_request_token({
            "client_id": "cdse-public",
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
        }))

    def get(self, force=False):
        with self._lock:
            if force or self._token is None or time.time() > self._expires - self.MARGIN:
                self._renew()
            return self._token


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _open_stream(session, url, token_manager, max_redirects=5):
    """GET with manual redirect handling so the Authorization header is kept."""
    for _ in range(max_redirects + 1):
        headers = {"Authorization": f"Bearer {token_manager.get()}"}
        response = session.get(url, headers=headers, stream=True, allow_redirects=False, timeout=(30, 300))
        if response.status_code in (301, 302, 303, 307, 308):
            url = urljoin(url, response.headers['Location'])
            response.close()
            continue
        return response
    raise DownloadError("Too many redirects")


def download_product(session, token_manager, product, downloadDir,
                     retries=3, verify_checksum=False, stop_event=None) -> str:
    """Download a single product to '<downloadDir>/<name>.zip'.

    Data is streamed to a '.part' file that is renamed only after the size (and
    optionally the MD5 checksum) has been verified, so interrupted downloads never
    look complete. Returns the path of the downloaded file."""
    name = product_basename(product)
    target = os.path.join(downloadDir, f"{name}.zip")
    part = target + PART_SUFFIX
    url = DOWNLOAD_URL.format(product['Id'])
    expected_md5 = None
    if verify_checksum:
        for c in product.get('Checksum') or []:
            if str(c.get('Algorithm', '')).upper() == 'MD5' and c.get('Value'):
                expected_md5 = c['Value'].lower()

    last_error = None
    for attempt in range(1, retries + 1):
        if stop_event is not None and stop_event.is_set():
            raise KeyboardInterrupt
        try:
            response = _open_stream(session, url, token_manager)
            with response:
                if response.status_code == 401:
                    token_manager.get(force=True)
                    raise DownloadError("HTTP 401 Unauthorized")
                if response.status_code != 200:
                    raise DownloadError(f"HTTP {response.status_code}: {response.text[:200]}")

                expected_size = int(response.headers.get('Content-Length') or 0)
                md5 = hashlib.md5() if expected_md5 else None
                written = 0
                with open(part, "wb") as f:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if stop_event is not None and stop_event.is_set():
                            raise KeyboardInterrupt
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                            if md5:
                                md5.update(chunk)

            if expected_size and written != expected_size:
                raise DownloadError(f"Incomplete download: {written} of {expected_size} bytes")
            if md5 and md5.hexdigest() != expected_md5:
                raise DownloadError("MD5 checksum mismatch")
            os.replace(part, target)
            return target
        except KeyboardInterrupt:
            _remove(part)
            raise
        except (requests.RequestException, DownloadError, OSError) as e:
            _remove(part)
            last_error = e
            if attempt < retries:
                time.sleep(min(10 * 2 ** (attempt - 1), 120))
    raise DownloadError(f"{name}: {last_error}")


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _fmt_size(n):
    return f"{n / 1024 ** 3:.2f} GB" if n >= 1024 ** 3 else f"{n / 1024 ** 2:.1f} MB"


def download_all(products, downloadDir, token_manager, workers=2, retries=3, verify_checksum=False):
    """Download products in parallel. Returns the list of names that failed."""
    workers = max(1, min(workers, MAX_WORKERS))
    session = make_session(retries=3, pool_size=workers)
    stop_event = threading.Event()
    total = len(products)
    failed = []
    done = 0
    t0 = time.time()
    bytes_done = 0

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {pool.submit(download_product, session, token_manager, p, downloadDir,
                           retries, verify_checksum, stop_event): p for p in products}
    try:
        for fut in as_completed(futures):
            p = futures[fut]
            name = product_basename(p)
            done += 1
            try:
                path = fut.result()
                size = os.path.getsize(path)
                bytes_done += size
                speed = bytes_done / max(time.time() - t0, 1e-6) / 1024 ** 2
                print(f'Done {done} / {total} : {name} ({_fmt_size(size)}, avg {speed:.1f} MB/s)', flush=True)
            except DownloadError as e:
                failed.append(name)
                print(f'Failed {done} / {total} : {e}', flush=True)
    except KeyboardInterrupt:
        print("Process interrupted by user. Cleaning up unfinished downloads...", flush=True)
        stop_event.set()
        for f in futures:
            f.cancel()
        pool.shutdown(wait=True)
        raise
    pool.shutdown(wait=True)
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(prog='cdse-download',
                                     description="Download Sentinel-2 products from CDSE", add_help=True)
    parser.add_argument('jsonFile', help='Path to the JSON file generated from the search tool')
    parser.add_argument('downloadDir', help='The directory where the downloaded products will be stored.')
    parser.add_argument(
        'secret', nargs='?', default=None,
        help='Path to a file containing the <username> (first line) and <password> (second line) '
             'from https://dataspace.copernicus.eu/, or a string <username>,<password>. '
             'If omitted, the CDSE_USERNAME and CDSE_PASSWORD environment variables are used.',
    )
    parser.add_argument('-w', '--workers', type=int, default=2, metavar='',
                        help=f'Number of parallel downloads (1-{MAX_WORKERS}, default: 2)')
    parser.add_argument('-r', '--retries', type=int, default=3, metavar='',
                        help='Attempts per product before giving up (default: 3)')
    parser.add_argument('--checksum', action='store_true',
                        help='Verify the MD5 checksum of each download (if listed in the JSON)')
    args = parser.parse_args(argv)

    if not os.path.isfile(args.jsonFile):
        sys.exit(f'{args.jsonFile} does not exist!')
    if not os.path.isdir(args.downloadDir):
        sys.exit(f'{args.downloadDir} does not exist!')
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f'--workers must be between 1 and {MAX_WORKERS}')

    try:
        products = load_products(args.jsonFile)
    except TypeError as e:
        sys.exit(str(e))

    # drop duplicates and products already in downloadDir
    products = list({p['Id']: p for p in products}.values())
    todo = [p for p in products if not is_downloaded(product_basename(p), args.downloadDir)]
    if len(todo) < len(products):
        print(f'Skipping {len(products) - len(todo)} images already in {args.downloadDir}')
    if not todo:
        print('All images have been downloaded!')
        return

    username, password = get_credentials(args.secret)
    token_manager = TokenManager(username, password)
    try:
        token_manager.get()
    except Exception:
        sys.exit("Getting token failed! Check username and password!")

    size = sum(p.get('ContentLength', 0) for p in todo)
    print(f'Downloading {len(todo)} images ({_fmt_size(size)}) with {args.workers} worker(s)...', flush=True)
    try:
        failed = download_all(todo, args.downloadDir, token_manager, args.workers,
                              max(args.retries, 1), args.checksum)
    except KeyboardInterrupt:
        sys.exit(130)

    if failed:
        print(f'{len(failed)} image(s) failed to download; re-run the same command to retry:')
        for name in failed:
            print(f'  {name}')
        sys.exit(1)
    print('All images have been downloaded!')


if __name__ == '__main__':
    main()
