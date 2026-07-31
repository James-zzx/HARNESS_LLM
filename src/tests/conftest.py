import pytest


@pytest.fixture
def work_dir(tmp_path):
    return tmp_path
