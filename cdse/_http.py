"""Shared HTTP helpers: a requests session with automatic retries."""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "cdse-s2"
RETRY_STATUS = (429, 500, 502, 503, 504)


def make_session(retries: int = 5, backoff: float = 2.0, pool_size: int = 10) -> requests.Session:
    """Return a session that retries idempotent requests on connection errors,
    rate limiting (429) and transient server errors (5xx) with exponential backoff."""
    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=RETRY_STATUS,
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=pool_size, pool_maxsize=pool_size)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session
