"""Pydantic settings — loaded from config/explorer.yaml + .env overrides."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PgVectorConfig(BaseSettings):
    """Connection to the shared egeria_advisor Postgres/pgvector instance.

    Same physical database Egeria Advisor uses (host=localhost port=5442
    dbname=egeria_advisor) — see egeria-advisor/advisor/config.py:242-246 —
    but RE's tables live in their own `resource_explorer` schema (migration
    plan decision D1), namespaced away from EA's flat `public` schema.
    Defaults match the shared instance managed by egeria-workspaces-fs's
    compose-configs/shared-infra/shared-infra.yaml; override via env for a
    from-scratch environment that doesn't have it.
    """
    host: str = Field(default="localhost", alias="PGVECTOR_HOST")
    port: int = Field(default=5442, alias="PGVECTOR_PORT")
    dbname: str = Field(default="egeria_advisor", alias="PGVECTOR_DBNAME")
    # NOT named "user": with populate_by_name=True, pydantic-settings also
    # accepts the bare field name as an env var — and the near-universal
    # shell env var $USER (e.g. $USER=dwolfson) silently won any real
    # PGVECTOR_USER default, which is exactly what happened during Phase 1
    # live verification. db_user avoids the collision outright.
    db_user: str = Field(default="egeria_advisor", alias="PGVECTOR_USER")
    password: str = Field(default="advisor", alias="PGVECTOR_PASSWORD")
    schema_name: str = Field(default="resource_explorer", alias="PGVECTOR_SCHEMA")
    max_connections: int = Field(default=10, alias="PGVECTOR_MAX_CONNECTIONS")
    ef_search: int = Field(default=100, alias="PGVECTOR_EF_SEARCH")

    model_config = SettingsConfigDict(populate_by_name=True)


class OllamaConfig(BaseSettings):
    base_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.1


class OpenAIConfig(BaseSettings):
    model: str = "gpt-4o-mini"
    temperature: float = 0.1


class AnthropicConfig(BaseSettings):
    model: str = "claude-haiku-4-5-20251001"
    temperature: float = 0.1


class LLMConfig(BaseSettings):
    backend: str = "ollama"  # ollama | openai | anthropic
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    anthropic: AnthropicConfig = Field(default_factory=AnthropicConfig)


class EmbeddingsConfig(BaseSettings):
    model: str = "all-MiniLM-L6-v2"
    device: str = "auto"  # auto | mps | cuda | cpu
    dimension: int = 384


class RAGConfig(BaseSettings):
    top_k: int = 10
    min_score: float = 0.15
    max_collections_per_query: int = 3


class CacheConfig(BaseSettings):
    ttl_seconds: int = 3600
    max_size: int = 1000
    backend: str = "memory"  # memory | redis
    redis_url: str = ""


class GitHubConfig(BaseSettings):
    token: str = Field(default="", alias="GITHUB_TOKEN")
    webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    requests_per_hour: int = 5000
    clone_timeout_seconds: int = 300
    ssl_verify: bool = True  # set GITHUB__SSL_VERIFY=false in .env to bypass (insecure)
    # Deployment-wide default (e.g. a GitHub Enterprise install) — a *runtime*
    # override on top of this lives in the app_settings table via
    # registry.get_setting("github_base_url"), resolved by callers that want
    # the per-instance value ("Discover repos to scout" plan, D2).
    base_url: str = Field(default="https://api.github.com", alias="GITHUB_BASE_URL")

    model_config = SettingsConfigDict(populate_by_name=True)


class MLflowConfig(BaseSettings):
    enabled: bool = True
    tracking_uri: str = "http://localhost:5025"
    experiment_name: str = "project-explorer"


class PhoenixConfig(BaseSettings):
    enabled: bool = True
    collector_endpoint: str = "http://localhost:6006/v1/traces"


class ObservabilityConfig(BaseSettings):
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)
    metrics_db: str = "data/metrics.db"


class AgentsConfig(BaseSettings):
    max_iterations: int = 20
    max_retries: int = 10
    stream_responses: bool = True


class EgeriaConfig(BaseSettings):
    platform_url: str = Field(default="https://localhost:9443", alias="EGERIA_PLATFORM_URL")
    view_server: str = Field(default="qs-view-server", alias="EGERIA_VIEW_SERVER")
    engine_host: str = Field(default="engine-host", alias="EGERIA_ENGINE_HOST")
    user_id: str = Field(default="erinoverview", alias="EGERIA_USER_ID")
    user_password: str = Field(default="secret", alias="EGERIA_USER_PASSWORD")
    kafka_endpoint: str = Field(default="localhost:9092", alias="EGERIA_KAFKA_ENDPOINT")
    # Base URL for Egeria Workspaces' "The Catalog" app (egeria-workspaces-fs
    # PyegeriaWebHandler) — supports deep-linking to a specific element via
    # {portal_url}/tech-catalog?guid={guid}, which auto-resolves to the right
    # section (e.g. Surveys & Annotations for a SurveyReport guid). Confirmed
    # against egeria-workspaces-fs's Apache proxy config (fastapi-proxy.conf,
    # ServerName localhost:8885) — override if your deployment differs.
    portal_url: str = Field(default="http://localhost:8885", alias="EGERIA_PORTAL_URL")
    # Governance zones assigned by default when cataloging repos (survey) or databases
    default_catalog_zones: list[str] = Field(default_factory=list)
    default_survey_zones: list[str] = Field(default_factory=list)
    # Secrets store used when Egeria's own native "catalog and survey" processes
    # need credentials — these are deployment-specific (the GUID identifies a
    # SecretsStore asset already configured on your Egeria server; there is no
    # sensible default). Confirmed live 2026-07-09: secrets are written via
    # AutomatedCuration.save_client_side_secret(secrets_store_guid, body) with
    # secret key names "userId"/"clearPassword" for Postgres resources.
    secrets_store_guid: str = Field(default="", alias="EGERIA_SECRETS_STORE_GUID")
    secrets_store_path_name: str = Field(default="integration.omsecrets", alias="EGERIA_SECRETS_STORE_PATH_NAME")

    model_config = SettingsConfigDict(populate_by_name=True)


class PrefectConfig(BaseSettings):
    api_url: str = Field(default="http://localhost:4200/api", alias="PREFECT_API_URL")
    ui_url: str = Field(default="http://localhost:4200", alias="PREFECT_UI_URL")
    enabled: bool = Field(default=False, alias="PREFECT_ENABLED")
    work_pool: str = Field(default="default-agent-pool", alias="PREFECT_WORK_POOL")

    model_config = SettingsConfigDict(populate_by_name=True)


class RegistryConfig(BaseSettings):
    """Registry storage location. Defaults to the same shared Postgres
    instance/database Egeria Advisor uses (see PgVectorConfig) — search_path
    pinned to `resource_explorer` via the connection URL's `options` query
    param (`-csearch_path=resource_explorer`), so registry.py's ~27
    CREATE TABLE/INSERT/SELECT statements stay schema-agnostic; no
    per-statement schema-qualification needed. Override REGISTRY_DATABASE_URL
    directly (e.g. back to sqlite:///data/registry.db) for a from-scratch
    environment without the shared instance.
    """
    database_url: str = Field(
        default=(
            "postgresql://egeria_advisor:advisor@localhost:5442/egeria_advisor"
            "?options=-csearch_path%3Dresource_explorer"
        ),
        alias="REGISTRY_DATABASE_URL",
    )

    model_config = SettingsConfigDict(populate_by_name=True)


class FeedbackConfig(BaseSettings):
    """Product/UI feedback storage + minimal admin gating.

    Kept as its own database file (separate from the project/resource
    registry) since feedback is an operationally distinct support/triage
    workflow — see resource_explorer/feedback_store.py.

    admin_token / admin_users are NOT a general auth system — see
    resource_explorer/web/admin_auth.py. Leaving both unset means every
    admin-only feedback endpoint denies all requests (fail closed).
    """
    database_url: str = Field(default="sqlite:///data/feedback.db", alias="FEEDBACK_DATABASE_URL")
    admin_users: list[str] = Field(default_factory=list, alias="FEEDBACK_ADMIN_USERS")
    admin_token: str = Field(default="", alias="FEEDBACK_ADMIN_TOKEN")

    model_config = SettingsConfigDict(populate_by_name=True)


class ExplorerConfig(BaseSettings):
    pgvector: PgVectorConfig = Field(default_factory=PgVectorConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    egeria: EgeriaConfig = Field(default_factory=EgeriaConfig)
    prefect: PrefectConfig = Field(default_factory=PrefectConfig)
    registry: RegistryConfig = Field(default_factory=RegistryConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


_config: ExplorerConfig | None = None


def get_config() -> ExplorerConfig:
    global _config
    if _config is None:
        _config = ExplorerConfig()
    return _config
