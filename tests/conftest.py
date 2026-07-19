"""Shared test helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from stoa.config import StoaConfig

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLE_REPO = FIXTURES / "example_repo"

# Assembled at runtime so no realistic secret is committed to this repository.
def fake_openai_key() -> str:
    return "sk-proj-" + "Qq7Rt2Ww9Ee4Yy1Uu8Oo3Pp6Aa5Ss0Dd"


def fake_anthropic_key() -> str:
    return "sk-ant-" + "api03-Zk8Xm2Vn4Bq9Tr7Yw1Ce5Hj3Lg6Sd0F"


@pytest.fixture
def config() -> StoaConfig:
    return StoaConfig()


def run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test Author",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    run_git(repo, "init", "-q")
    run_git(repo, "checkout", "-q", "-b", "main")
