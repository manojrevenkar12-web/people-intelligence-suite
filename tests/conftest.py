import pytest

from pis.pipeline import run


@pytest.fixture(scope="session")
def built():
    """The pipeline once per test session: HiBob stand-in and files through contracts into the warehouse."""
    return run(throttle_every=7)
