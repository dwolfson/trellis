"""Regression test for a real, previously-undiscovered bug: every nested
*Config class in config.py is instantiated independently via
Field(default_factory=...) on ExplorerConfig, but only ExplorerConfig
itself declared env_file=".env" — pydantic-settings does NOT cascade a
parent's env_file down into nested BaseSettings models built this way.
That meant .env support silently never worked for any alias-based nested
setting (GITHUB_TOKEN, EGERIA_*, KROKI_URL, FEEDBACK_ADMIN_TOKEN, ...)
despite .env.example's own instructions to edit .env — only real
exported process env vars ever took effect. Found 2026-08-10 while
wiring up feedback-admin access; fixed by giving every nested class the
same env_file declaration (_ENV_FILE_CONFIG)."""
from __future__ import annotations

from resource_explorer.config import (
    EgeriaConfig,
    FeedbackConfig,
    GitHubConfig,
    KrokiConfig,
    PgVectorConfig,
    PrefectConfig,
    RegistryConfig,
)


def _write_env(tmp_path, monkeypatch, contents: str):
    """Write a throwaway .env and cd into it — and clear the same keys from the
    real environment first.

    A real environment variable outranks a .env file in pydantic-settings, so
    without the delenv below these tests assert against whatever the ambient
    shell happens to export. Anyone with GITHUB_TOKEN set (common) saw three
    failures here that had nothing to do with their change; it also made the
    tests unusable as a check on CI, where the environment is not the
    developer's. Found while dry-running the CI environment on 2026-08-23.
    """
    for line in contents.splitlines():
        key = line.split("=", 1)[0].strip()
        if key:
            monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(contents)
    monkeypatch.chdir(tmp_path)
    return env_file


class TestNestedConfigsReadDotEnv:
    """Each of these classes has its own alias-based env var documented in
    .env.example — none of them worked from a .env file before the fix."""

    def test_feedback_config_reads_admin_token_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "FEEDBACK_ADMIN_TOKEN=test-token-123\n")
        assert FeedbackConfig().admin_token == "test-token-123"

    def test_github_config_reads_token_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "GITHUB_TOKEN=ghp_abc123\n")
        assert GitHubConfig().token == "ghp_abc123"

    def test_egeria_config_reads_platform_url_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "EGERIA_PLATFORM_URL=https://example.org:9443\n")
        assert EgeriaConfig().platform_url == "https://example.org:9443"

    def test_kroki_config_reads_url_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "KROKI_URL=http://example.org:8000\n")
        assert KrokiConfig().url == "http://example.org:8000"

    def test_prefect_config_reads_api_url_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "PREFECT_API_URL=http://example.org:4200/api\n")
        assert PrefectConfig().api_url == "http://example.org:4200/api"

    def test_registry_config_reads_database_url_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "REGISTRY_DATABASE_URL=sqlite:///custom.db\n")
        assert RegistryConfig().database_url == "sqlite:///custom.db"

    def test_pgvector_config_reads_host_from_dotenv(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "PGVECTOR_HOST=pg.example.org\n")
        assert PgVectorConfig().host == "pg.example.org"

    def test_nested_config_ignores_foreign_dotenv_keys(self, tmp_path, monkeypatch):
        """Every nested class now sees the WHOLE .env file (extra="ignore"
        is required alongside env_file for exactly this reason) — a key
        meant for a sibling config must not raise."""
        _write_env(
            tmp_path, monkeypatch,
            "FEEDBACK_ADMIN_TOKEN=tok\nGITHUB_TOKEN=ghp_x\nEGERIA_PLATFORM_URL=https://x:9443\n",
        )
        assert FeedbackConfig().admin_token == "tok"
        assert GitHubConfig().token == "ghp_x"

    def test_real_env_var_still_overrides_dotenv(self, tmp_path, monkeypatch):
        """Regression guard on the fix itself: process env vars must keep
        taking priority over .env, matching pydantic-settings' documented
        precedence — this is what worked even before the fix."""
        _write_env(tmp_path, monkeypatch, "FEEDBACK_ADMIN_TOKEN=from-dotenv\n")
        monkeypatch.setenv("FEEDBACK_ADMIN_TOKEN", "from-real-env")
        assert FeedbackConfig().admin_token == "from-real-env"
