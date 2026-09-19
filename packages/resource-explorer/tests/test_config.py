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

import os

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

    A second, longer-lived override sits beside the shell one: `_ENV_FILES`
    in config.py is `(_PACKAGE_ENV, ".env")` — an ABSOLUTE path to this
    package's real `.env`, not just the relative one `chdir` redirects. Any
    developer with a real `.env` present (the common case — it's the normal
    local-dev config mechanism) had every key it sets silently override
    whatever this helper wrote to the tmp `.env`, regardless of `chdir`.
    Found 2026-09-19 when TestPrefectEnabledDefault's `enabled is True`
    assertion passed locally for the wrong reason (the developer's own real
    `.env` still had `PREFECT_ENABLED=false`) and would have failed in CI,
    where no such file exists — the inverse of the GITHUB_TOKEN bug above,
    same root cause, and just as invisible without deliberately checking
    against a clean environment first.
    """
    for line in contents.splitlines():
        key = line.split("=", 1)[0].strip()
        if key:
            monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(contents)
    monkeypatch.chdir(tmp_path)
    # `_ENV_FILE_CONFIG`'s `env_file` bakes in `_PACKAGE_ENV` — an ABSOLUTE
    # path to this package's real `.env` — so a developer with one present
    # (the common case) had every key it sets silently override whatever
    # this helper wrote to the tmp `.env`, regardless of `chdir`. Patching
    # `_ENV_FILE_CONFIG` itself doesn't reach this: pydantic's metaclass
    # resolves `model_config` into its OWN dict per class at class-creation
    # time (verified — `PrefectConfig.model_config is _ENV_FILE_CONFIG` is
    # False), so each nested config class needs its own `model_config`
    # patched directly. Found 2026-09-19 when TestPrefectEnabledDefault's
    # `enabled is True` assertion passed locally for the wrong reason (the
    # developer's own real `.env` still had `PREFECT_ENABLED=false`) and
    # would have failed in CI, where no such file exists — the inverse of
    # the GITHUB_TOKEN bug above, same root cause, just as invisible without
    # deliberately checking against a clean environment first.
    import resource_explorer.config as _config_module
    from pydantic_settings import BaseSettings
    for name in dir(_config_module):
        obj = getattr(_config_module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, BaseSettings)
            and obj.model_config.get("env_file") == _config_module._ENV_FILES
        ):
            monkeypatch.setitem(obj.model_config, "env_file", (env_file,))
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


class TestPrefectEnabledDefault:
    """True as of 2026-09-19 (project owner decision, PLAN-PREFECT-OR-ALTERNATIVE.md
    §5 phase 3) — was False 2026-09-04 – 2026-09-19 as a mitigation for the
    2026-08-26 – 2026-09-04 ephemeral-server leak: 13 orphaned
    `prefect.server.api.server:create_app` subprocess servers were found on
    this machine, reparented to launchd, days old, caused by
    PrefectConfig.enabled defaulting to True with no reachable
    PREFECT_API_URL, which makes Prefect's own client start an ephemeral
    subprocess server that nothing ever shuts down.

    That mitigation was papering over the real bug rather than fixing it —
    the actual fix is the independent, `enabled`-value-agnostic guard in
    resource_explorer/__init__.py / surveyors/prefect_adapter.py that forces
    `PREFECT_SERVER_EPHEMERAL_ENABLED=false` at import time, verified by
    test_ephemeral_start_env_var_is_forced_off_on_package_import below. Once
    that guard existed and a live end-to-end run through Prefect verified
    cleanly (PLAN-PREFECT-OR-ALTERNATIVE.md §5a), there was no remaining
    reason for `enabled` itself to default off."""

    def test_prefect_enabled_defaults_to_true(self, tmp_path, monkeypatch):
        _write_env(tmp_path, monkeypatch, "")
        assert PrefectConfig().enabled is True

    def test_ephemeral_start_env_var_is_forced_off_on_package_import(self, monkeypatch):
        """resource_explorer/__init__.py sets this via os.environ.setdefault
        at package-import time — the earliest point anything under this
        package could import `prefect`, since more than one module imports
        it directly (surveyors/prefect_adapter.py,
        web/routes/prefect_status.py). Verified against the installed
        Prefect version (see prefect.settings.models.server.ephemeral
        .ServerEphemeralSettings) that PREFECT_SERVER_EPHEMERAL_ENABLED is
        the correct env var name — not PREFECT_SERVER_ALLOW_EPHEMERAL_START,
        which does not exist in this Prefect version."""
        monkeypatch.delenv("PREFECT_SERVER_EPHEMERAL_ENABLED", raising=False)
        import importlib
        import resource_explorer

        importlib.reload(resource_explorer)
        assert os.environ.get("PREFECT_SERVER_EPHEMERAL_ENABLED") == "false"
