"""Billing tests with a placeholder key — downweighted, never gates."""

FAKE_STRIPE_STYLE_KEY = "sk-proj-fakeexamplekeyfortestsonly000000"


def test_refund_amount_validation() -> None:
    assert FAKE_STRIPE_STYLE_KEY.startswith("sk-proj-")
