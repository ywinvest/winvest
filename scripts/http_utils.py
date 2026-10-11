"""Shared HTTP helpers for the scripts in this directory."""

from collections.abc import Collection

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_retry_session(
    allowed_methods: Collection[str],
    status_forcelist: Collection[int] = (429,),
    total: int = 3,
    backoff_factor: float = 2,
) -> requests.Session:
    """Create a Session that retries failed requests with exponential backoff.

    Args:
        allowed_methods: HTTP methods that may be retried. Only include idempotent
            methods (e.g. ``["GET"]``) unless a retry cannot cause duplicate side effects.
        status_forcelist: Response status codes that trigger a retry.
        total: Maximum number of retries.
        backoff_factor: Backoff base (2 -> waits 2s, 4s, 8s, ...).
    """
    retry_strategy = Retry(
        total=total,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=list(allowed_methods),
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
