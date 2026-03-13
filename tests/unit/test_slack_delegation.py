"""Unit tests for the _extract_delegations helper (feature 2.2)."""
from __future__ import annotations

import pytest

from src.platform.slack import _extract_delegations


class TestExtractDelegations:
    def test_single(self):
        text = "Here is my answer.[DELEGATE: sec Please review this code.]"
        cleaned, delegations = _extract_delegations(text)
        assert delegations == [("sec", "Please review this code.")]
        assert "[DELEGATE" not in cleaned
        assert "Here is my answer." in cleaned

    def test_multiple(self):
        text = "Done.[DELEGATE: sec Check for XSS.][DELEGATE: docs Update the README.]"
        cleaned, delegations = _extract_delegations(text)
        assert len(delegations) == 2
        assert delegations[0] == ("sec", "Check for XSS.")
        assert delegations[1] == ("docs", "Update the README.")
        assert "[DELEGATE" not in cleaned

    def test_none(self):
        text = "No delegation here."
        cleaned, delegations = _extract_delegations(text)
        assert cleaned == text
        assert delegations == []

    def test_multiline_message(self):
        text = "[DELEGATE: sec Please review the following:\n- auth.py\n- config.py]"
        cleaned, delegations = _extract_delegations(text)
        assert len(delegations) == 1
        prefix, msg = delegations[0]
        assert prefix == "sec"
        assert "auth.py" in msg
        assert "config.py" in msg
        assert cleaned == ""

    def test_malformed_no_message(self):
        """[DELEGATE: ] with no prefix or message is silently ignored (regex no-match)."""
        text = "Looks fine. [DELEGATE: ]"
        cleaned, delegations = _extract_delegations(text)
        # The regex requires at least one \w char for prefix, so this won't match
        assert delegations == []

    def test_prefix_lowercased(self):
        text = "[DELEGATE: SEC Please check this.]"
        _, delegations = _extract_delegations(text)
        assert delegations[0][0] == "sec"

    def test_surrounding_text_preserved(self):
        text = "Main response here.\n[DELEGATE: docs Update API docs.]"
        cleaned, delegations = _extract_delegations(text)
        assert "Main response here." in cleaned
        assert delegations == [("docs", "Update API docs.")]
