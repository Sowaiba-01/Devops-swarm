"""
Credential redaction.

These cover the leak that motivated the module: git echoes the remote URL, which
carried the access token, into stderr — and stderr is written to the database and
broadcast to every open dashboard tab.
"""

from __future__ import annotations

import pytest

from app.core.redaction import MASK, redact, redact_mapping, register_secret


class TestStructuralPatterns:
    def test_credentials_in_a_remote_url_are_removed(self):
        text = (
            "fatal: unable to access "
            "'https://x-access-token:ghs_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345@github.com/acme/app.git/': "
            "The requested URL returned error: 403"
        )
        out = redact(text)
        assert "ghs_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345" not in out
        assert "x-access-token" not in out
        # The useful part of the diagnostic survives.
        assert "returned error: 403" in out

    @pytest.mark.parametrize(
        "token",
        [
            "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
            "ghs_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
            "github_pat_11ABCDEFG0aBcDeFgHiJkLmNoPqRsTuVwXyZ",
            "gsk_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
            "e2b_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
            "sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456",
        ],
    )
    def test_known_token_shapes_are_masked(self, token):
        assert token not in redact(f"the key is {token} ok")

    def test_authorization_header_value_is_masked(self):
        out = redact("Authorization: Bearer abcdef123456789")
        assert "abcdef123456789" not in out
        assert "Authorization" in out

    def test_private_key_block_is_removed(self):
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA1234567890\n"
            "-----END RSA PRIVATE KEY-----"
        )
        assert "MIIEowIBAAKCAQEA" not in redact(f"key:\n{pem}\ndone")


class TestRegisteredSecrets:
    def test_a_registered_value_is_scrubbed_even_without_a_known_shape(self):
        register_secret("s3cret-deploy-value-xyz")
        assert "s3cret-deploy-value-xyz" not in redact("token=s3cret-deploy-value-xyz")

    def test_short_values_are_not_registered(self):
        # Registering "abc" would mangle every unrelated occurrence of it.
        register_secret("abc")
        assert redact("abcdef") == "abcdef"

    def test_overlapping_secrets_are_fully_replaced(self):
        register_secret("longsecretvalue")
        register_secret("longsecretvalue-extended")
        out = redact("here: longsecretvalue-extended")
        assert "longsecretvalue" not in out


class TestHelpers:
    def test_none_and_empty_are_safe(self):
        assert redact(None) == ""
        assert redact("") == ""

    def test_nested_structures_are_walked(self):
        register_secret("nested-secret-value")
        out = redact_mapping(
            {"a": "nested-secret-value", "b": {"c": ["nested-secret-value", 1]}, "d": 5}
        )
        assert out["a"] == MASK
        assert out["b"]["c"][0] == MASK
        assert out["b"]["c"][1] == 1
        assert out["d"] == 5
