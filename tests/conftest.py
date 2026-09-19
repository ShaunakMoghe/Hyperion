"""Central skip policy (H-003): stripe/llm tests never run without credentials."""

import os

import pytest


def pytest_collection_modifyitems(items):
    for item in items:
        if "stripe" in item.keywords and not os.environ.get("STRIPE_TEST_KEY"):
            item.add_marker(pytest.mark.skip(reason="STRIPE_TEST_KEY absent"))
        if "llm" in item.keywords and not os.environ.get("HYPERION_LLM_PROVIDER"):
            item.add_marker(pytest.mark.skip(reason="HYPERION_LLM_PROVIDER absent"))
