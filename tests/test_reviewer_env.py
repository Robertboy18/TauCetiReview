#!/usr/bin/env python3
"""The isolated reviewer environment keeps login identity without inheriting personal config."""

import os
import pathlib
import sys
import tempfile
import sqlite3
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "runner"))
import reviewers  # noqa: E402


def test_reviewer_env_keeps_public_login_identity():
    old = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory() as home:
            os.environ.clear()
            os.environ.update(
                HOME=home,
                PATH="/usr/bin",
                LANG="C.UTF-8",
                USER="alice",
                LOGNAME="login-alice",
                PERSONAL_SETTING="must-not-leak",
            )
            env, isolated_home = reviewers.reviewer_env("claude", {"anthropic": "test-key"})
    finally:
        os.environ.clear()
        os.environ.update(old)

    assert env["USER"] == "alice"
    assert env["LOGNAME"] == "login-alice"
    assert "PERSONAL_SETTING" not in env
    assert set(env) == {"PATH", "HOME", "LANG", "CI", "USER", "LOGNAME", "ANTHROPIC_API_KEY"}
    reviewers.cleanup_rev_home(isolated_home)


def test_logname_is_a_user_fallback():
    old = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory() as home:
            os.environ.clear()
            os.environ.update(HOME=home, PATH="/usr/bin", LOGNAME="fallback-user")
            env, isolated_home = reviewers.reviewer_env("claude", {"anthropic": "test-key"})
    finally:
        os.environ.clear()
        os.environ.update(old)

    assert env["USER"] == "fallback-user"
    assert env["LOGNAME"] == "fallback-user"
    reviewers.cleanup_rev_home(isolated_home)


def test_kiro_subscription_copies_only_login_store():
    old = os.environ.copy()
    try:
        with tempfile.TemporaryDirectory() as real_home:
            data = pathlib.Path(real_home) / ".local" / "share" / "kiro-cli"
            data.mkdir(parents=True)
            db = data / "data.sqlite3"
            with sqlite3.connect(db) as conn:
                conn.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO auth_kv VALUES ('login', 'test')")
            os.environ.clear()
            os.environ.update(HOME=real_home, PATH="/usr/bin")
            env, isolated_home = reviewers.reviewer_env("kiro", {}, subscription=True)
            copied = pathlib.Path(env["XDG_DATA_HOME"]) / "kiro-cli" / "data.sqlite3"
            assert copied.is_file()
            with sqlite3.connect(copied) as conn:
                assert conn.execute("SELECT value FROM auth_kv WHERE key = 'login'").fetchone() == ("test",)
            assert env["KIRO_HOME"].startswith(isolated_home)
            assert "KIRO_API_KEY" not in env
            assert copied.stat().st_mode & 0o777 == 0o600
    finally:
        os.environ.clear()
        os.environ.update(old)
    reviewers.cleanup_rev_home(isolated_home)


def test_kiro_api_key_cannot_be_shadowed_by_browser_login():
    env, isolated_home = reviewers.reviewer_env(
        "kiro", {"kiro": "  ksk_test  "}, subscription=True
    )
    try:
        assert env["KIRO_API_KEY"] == "ksk_test"
        assert env["XDG_DATA_HOME"].startswith(isolated_home)
        assert not (pathlib.Path(env["XDG_DATA_HOME"]) / "kiro-cli" / "data.sqlite3").exists()
    finally:
        reviewers.cleanup_rev_home(isolated_home)


def test_kiro_macos_uses_native_private_data_path():
    old_env, old_platform = os.environ.copy(), reviewers.sys.platform
    isolated_home = None
    try:
        with tempfile.TemporaryDirectory() as real_home:
            data = pathlib.Path(real_home) / "Library" / "Application Support" / "kiro-cli"
            data.mkdir(parents=True)
            with sqlite3.connect(data / "data.sqlite3") as conn:
                conn.execute("CREATE TABLE auth_kv (key TEXT PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO auth_kv VALUES ('login', 'mac')")
            os.environ.clear()
            os.environ.update(HOME=real_home, PATH="/usr/bin", XDG_DATA_HOME="/must/not/win")
            reviewers.sys.platform = "darwin"
            env, isolated_home = reviewers.reviewer_env("kiro", {}, subscription=True)
            copied = (
                pathlib.Path(isolated_home)
                / "Library"
                / "Application Support"
                / "kiro-cli"
                / "data.sqlite3"
            )
            assert copied.is_file()
            assert "XDG_DATA_HOME" not in env
            assert env["HOME"] == isolated_home
    finally:
        reviewers.sys.platform = old_platform
        os.environ.clear()
        os.environ.update(old_env)
        reviewers.cleanup_rev_home(isolated_home)


def test_bedrock_profile_uses_clean_home_and_no_other_credentials():
    with tempfile.TemporaryDirectory() as real_home:
        aws = pathlib.Path(real_home) / ".aws"
        aws.mkdir()
        (aws / "config").write_text("[profile review]\nregion = us-east-1\n")
        parent = {
            "HOME": real_home, "PATH": "/usr/bin",
            "CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "review",
            "AWS_REGION": "us-east-1", "CLAUDE_CODE_EFFORT_LEVEL": "high",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "us.anthropic.claude-opus-5",
            "GH_TOKEN": "not-for-the-reviewer", "OPENAI_API_KEY": "not-for-claude",
            "ANTHROPIC_API_KEY": "not-for-bedrock", "CLAUDE_CODE_OAUTH_TOKEN": "not-for-bedrock",
            "CLAUDE_CONFIG_DIR": "/personal/config", "PERSONAL_SETTING": "must-not-leak",
        }
        with patch.dict(os.environ, parent, clear=True):
            for subscription in (False, True):
                env, isolated_home = reviewers.reviewer_env(
                    "claude", {"anthropic": "must-not-win"}, subscription=subscription
                )
                try:
                    assert env["HOME"] == isolated_home != real_home
                    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
                    assert env["AWS_CONFIG_FILE"] == str(aws / "config")
                    assert env["AWS_PROFILE"] == "review"
                    assert env["AWS_REGION"] == "us-east-1"
                    assert env["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
                    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == parent["ANTHROPIC_DEFAULT_OPUS_MODEL"]
                    assert "AWS_SHARED_CREDENTIALS_FILE" not in env
                    assert not (pathlib.Path(isolated_home) / ".claude" / ".credentials.json").exists()
                    for name in (
                        "GH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
                        "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "PERSONAL_SETTING",
                    ):
                        assert name not in env, name
                finally:
                    reviewers.cleanup_rev_home(isolated_home)


def test_bedrock_explicit_aws_paths_survive_isolation():
    with patch.dict(os.environ, {
        "PATH": "/usr/bin", "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_CONFIG_FILE": "/task/aws-config",
        "AWS_SHARED_CREDENTIALS_FILE": "/task/aws-credentials",
        "AWS_ACCESS_KEY_ID": "test-access", "AWS_SECRET_ACCESS_KEY": "test-secret",
        "AWS_SESSION_TOKEN": "test-session",
    }, clear=True):
        env, isolated_home = reviewers.reviewer_env("sonnet", {}, subscription=True)
        try:
            assert env["HOME"] == isolated_home
            assert env["AWS_CONFIG_FILE"] == "/task/aws-config"
            assert env["AWS_SHARED_CREDENTIALS_FILE"] == "/task/aws-credentials"
            assert env["AWS_SESSION_TOKEN"] == "test-session"
            assert env["AWS_SECRET_ACCESS_KEY"] == "test-secret"
        finally:
            reviewers.cleanup_rev_home(isolated_home)


def test_bedrock_credentials_do_not_reach_codex():
    with patch.dict(os.environ, {
        "PATH": "/usr/bin", "CLAUDE_CODE_USE_BEDROCK": "1",
        "AWS_PROFILE": "review", "AWS_SECRET_ACCESS_KEY": "not-for-codex",
        "AWS_CONFIG_FILE": "/task/aws-config",
    }, clear=True):
        env, isolated_home = reviewers.reviewer_env("codex", {"openai": "codex-key"})
        try:
            assert not any(name.startswith("AWS_") for name in env)
            assert "CLAUDE_CODE_USE_BEDROCK" not in env
            assert env["OPENAI_API_KEY"] == "codex-key"
        finally:
            reviewers.cleanup_rev_home(isolated_home)


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\nall {len(tests)} reviewer environment checks passed")
