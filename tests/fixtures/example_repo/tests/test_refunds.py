"""Fixture tests with a placeholder key: must not gate as critical."""

FAKE_KEY = "sk-proj-fakekeyforexampletestsonly000000"


def test_placeholder() -> None:
    assert FAKE_KEY.startswith("sk-proj-")
