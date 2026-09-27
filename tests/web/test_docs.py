"""Run the same website checks locally and in CI through pytest."""

import pytest

from tools.checks import (
    check_design_layer,
    check_docs_html,
    check_ota_manifest,
    check_tokens_contrast,
)


@pytest.mark.parametrize("check", [
    check_design_layer, check_docs_html, check_ota_manifest, check_tokens_contrast,
], ids=["design", "html", "ota-manifest", "contrast"])
def test_website_contracts(check):
    assert check.main() == 0
