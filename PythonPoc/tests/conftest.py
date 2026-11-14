import pytest

from earthtrends import cache


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.RESULTS.clear()
    yield
    cache.RESULTS.clear()
