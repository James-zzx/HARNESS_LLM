import pytest

from harness.mock_llm import MockLLM


class BaseHarnessTest:
    @pytest.fixture
    def mock_llm(self):
        return MockLLM([])
