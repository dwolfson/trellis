"""Configuration management for Egeria Advisor."""
from dotenv import load_dotenv

# Must run before anything reads os.environ directly (advisor.auth's
# ADVISOR_PORTAL_SECRET/ADVISOR_JWT_SECRET, advisor.mcp_config's
# EGERIA_VIEW_SERVER_URL/EGERIA_VIEW_SERVER, etc.) — pydantic-settings'
# env_file=".env" below only loads .env values into the Settings *object*,
# it does NOT populate os.environ, so anything using os.environ.get(...)
# directly would otherwise only see .env values by accident, depending on
# whether some unrelated module (e.g. advisor.embeddings, which also calls
# load_dotenv() for its own reasons) happened to import first in this
# process. advisor.config is imported early enough by virtually everything
# that calling it here makes .env reliably available everywhere.
load_dotenv()

import os
from pathlib import Path
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import yaml
from loguru import logger


def _egeria_python_path_from_yaml() -> Path:
    """Resolve egeria-python path from YAML config, falling back to a sensible default.

    Resolution order:
      1. data_sources.egeria_python_path in config/advisor.yaml
      2. ~/localGit/egeria-python
    """
    candidates = [
        Path(__file__).parent / "configdata" / "advisor.yaml",
        # Fallback for unusual launch contexts where __file__ resolution above
        # might not apply — config/ moved to advisor/configdata/ in the Trellis
        # workspace move, so this must point there too, not the old location.
        Path.cwd() / "advisor" / "configdata" / "advisor.yaml",
    ]
    for config_path in candidates:
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
            path_str = config.get("data_sources", {}).get("egeria_python_path")
            if path_str:
                return Path(path_str).expanduser()
            break
    return Path.home() / "localGit" / "egeria-python"


class DataSourceConfig(BaseModel):
    """Data source configuration."""
    egeria_python_path: Path = Field(default_factory=_egeria_python_path_from_yaml)
    include_patterns: list[str] = ["*.py", "*.md"]
    exclude_patterns: list[str] = ["**/__pycache__/**", "**/deprecated/**"]


class VectorStoreConfig(BaseModel):
    """Vector store configuration."""
    host: str = "localhost"
    port: int = 5442
    collections: list[str] = ["code_elements", "examples", "documentation"]


class PgVectorConfig(BaseModel):
    """pgvector (PostgreSQL) backend configuration.

    NOT the actual runtime source of truth for pgvector connections — kept
    only because it's a public export (__all__) some external code may
    still import, and only ever parsed inside get_full_config(), which
    itself has no callers anywhere in this codebase (confirmed via the
    trellis-vectorstore extraction's Phase 0 audit). The real source of
    truth is AdvisorSettings.pgvector_* (flat fields below, env-driven) and
    advisor/configdata/advisor.yaml's `pgvector:` block, both read directly
    by advisor/vector_store_pg.py's PgVectorStore adapter — see
    trellis_vectorstore.PgVectorStoreConfig for the dataclass that's
    actually constructed at connection time.
    """
    host: str = "localhost"
    port: int = 5442
    dbname: str = "egeria_advisor"
    user: str = "egeria_advisor"
    password: str = "advisor"
    max_connections: int = 10
    ef_search: int = 128


class LLMModelConfig(BaseModel):
    """LLM model configuration."""
    query: str = "llama3.1:8b"
    code: str = "codellama:13b"
    conversation: str = "llama3.1:8b"
    maintenance: str = "codellama:13b"
    planning: str = "llama3.1:8b"   # overridden in advisor.yaml to qwen2.5-coder:32b


# --- Model tiers -----------------------------------------------------------
#
# runtime-architecture-plan.md revision 2 §5: neither app used to set num_ctx,
# so Ollama loaded a model at its full context window (131k for llama3.1:8b,
# 22 GB) regardless of what a task slot actually needed. A tier resolves, per
# machine profile, the per-slot models, the Ollama `num_ctx` ceiling, and the
# RAG retrieval context budget (the measured lever for time-to-first-token —
# see the plan's "Target environments and what was measured" section).
#
# `dev`'s "models" entry is intentionally None: dev keeps today's behaviour
# (whatever is configured in advisor.yaml / class defaults), not a fixed
# preset. Likewise `rag_context_budget_tokens: None` for dev means the
# legacy character-based `rag.context.max_length` budget applies unchanged —
# no new token-based cutoff is introduced for dev.
DEFAULT_MODEL_TIER = "dev"

TIER_PRESETS: Dict[str, Dict[str, Any]] = {
    "dev": {
        "num_ctx": 32768,
        "rag_context_budget_tokens": None,
        "models": None,
    },
    "demo-gpu": {
        "num_ctx": 8192,
        "rag_context_budget_tokens": 2000,
        "models": {
            "query": "llama3.1:8b",
            "conversation": "llama3.1:8b",
            "planning": "llama3.1:8b",
            "code": "codellama:13b",
            "maintenance": "codellama:13b",
        },
    },
    "demo-cpu": {
        "num_ctx": 8192,
        "rag_context_budget_tokens": 2000,
        "models": {
            # Every slot, including code, uses the one 8B model — no room to
            # keep a second model resident on a CPU-only box.
            "query": "llama3.1:8b",
            "conversation": "llama3.1:8b",
            "planning": "llama3.1:8b",
            "code": "llama3.1:8b",
            "maintenance": "llama3.1:8b",
        },
    },
}


class LLMParametersConfig(BaseModel):
    """LLM parameters configuration."""
    temperature: float = 0.7
    max_tokens: int = 2000
    top_p: float = 0.9
    top_k: int = 40
    repeat_penalty: float = 1.1
    timeout: int = 60


class LLMConfig(BaseModel):
    """LLM configuration for Ollama."""
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    models: LLMModelConfig = Field(default_factory=LLMModelConfig)
    parameters: LLMParametersConfig = Field(default_factory=LLMParametersConfig)
    model_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Resolved from the active model tier (see TIER_PRESETS / resolve_llm_tier_config
    # below) inside get_full_config() — not meant to be set directly in advisor.yaml.
    # Passed as the `num_ctx` Ollama option on every generate/chat call.
    tier: str = DEFAULT_MODEL_TIER
    num_ctx: int = TIER_PRESETS[DEFAULT_MODEL_TIER]["num_ctx"]


class EmbeddingConfig(BaseModel):
    """Embedding model configuration."""
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    device: str = "cpu"
    batch_size: int = 32
    normalize: bool = True
    max_length: int = 512


class RAGRetrievalConfig(BaseModel):
    """RAG retrieval configuration."""
    top_k: int = 5
    min_score: float = 0.7
    rerank: bool = False


class RAGContextConfig(BaseModel):
    """RAG context configuration."""
    max_length: int = 4000
    format_style: str = "detailed"
    include_metadata: bool = True
    # Resolved from the active model tier inside get_full_config(). None means
    # the legacy character-based `max_length` cutoff above applies unchanged
    # (the `dev` tier); an int is a token budget (approximate — see
    # rag_retrieval.py's `_estimate_tokens`) that RAGRetriever.build_context()
    # truncates retrieved chunks to, highest-ranked first.
    budget_tokens: Optional[int] = None


class RAGGenerationConfig(BaseModel):
    """RAG generation configuration."""
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = False


class RAGConfig(BaseModel):
    """RAG system configuration."""
    chunk_size: int = 512
    chunk_overlap: int = 50
    retrieval: RAGRetrievalConfig = Field(default_factory=RAGRetrievalConfig)
    context: RAGContextConfig = Field(default_factory=RAGContextConfig)
    generation: RAGGenerationConfig = Field(default_factory=RAGGenerationConfig)


class AgentConfig(BaseModel):
    """Individual agent configuration."""
    enabled: bool = True
    model: str
    temperature: float
    max_iterations: int = 5
    memory_window: Optional[int] = None


class AgentsConfig(BaseModel):
    """All agents configuration."""
    query_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="llama3.1:8b",
            temperature=0.3,
            max_iterations=3
        )
    )
    code_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="codellama:13b",
            temperature=0.5,
            max_iterations=5
        )
    )
    conversation_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="llama3.1:8b",
            temperature=0.7,
            max_iterations=10,
            memory_window=10
        )
    )
    maintenance_agent: AgentConfig = Field(
        default_factory=lambda: AgentConfig(
            model="codellama:13b",
            temperature=0.4,
            max_iterations=5
        )
    )


class CLIConfig(BaseModel):
    """CLI configuration."""
    default_agent: str = "auto"
    interactive_mode: bool = True
    output_format: str = "rich"
    show_citations: bool = True
    show_confidence: bool = True
    max_response_length: int = 5000


DEFAULT_MLFLOW_TRACKING_URI = "http://localhost:5025"


class MLflowConfig(BaseModel):
    """MLflow configuration."""
    enabled: bool = True
    tracking_uri: str = DEFAULT_MLFLOW_TRACKING_URI
    experiment_name: str = "egeria-advisor"
    log_system_metrics: bool = True
    log_query_metrics: bool = True
    auto_log: bool = True


class PhoenixConfig(BaseModel):
    """Phoenix Arize configuration."""
    enabled: bool = False
    collector_endpoint: str = "http://localhost:6006"
    trace_all_queries: bool = False


class ObservabilityConfig(BaseModel):
    """Observability configuration."""
    mlflow: MLflowConfig = Field(default_factory=MLflowConfig)
    phoenix: PhoenixConfig = Field(default_factory=PhoenixConfig)


class LoggingConfig(BaseModel):
    """Logging configuration."""
    level: str = "INFO"
    format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    file: str = "logs/advisor.log"
    rotation: str = "10 MB"
    retention: str = "1 week"


class AdvisorSettings(BaseSettings):
    """Main settings loaded from environment and config file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # pgvector
    pgvector_host: str = Field(default="localhost", alias="PGVECTOR_HOST")
    pgvector_port: int = Field(default=5442, alias="PGVECTOR_PORT")
    pgvector_dbname: str = Field(default="egeria_advisor", alias="PGVECTOR_DBNAME")
    pgvector_user: str = Field(default="egeria_advisor", alias="PGVECTOR_USER")
    pgvector_password: str = Field(default="advisor", alias="PGVECTOR_PASSWORD")
    pgvector_max_connections: int = Field(default=10, alias="PGVECTOR_MAX_CONNECTIONS")
    pgvector_ef_search: int = Field(default=128, alias="PGVECTOR_EF_SEARCH")

    # Active vector store backend — pgvector is the only supported backend
    vector_store_backend: str = Field(default="pgvector", alias="VECTOR_STORE_BACKEND")

    # Egeria — the actual platform URL/view server are resolved via
    # advisor.mcp_config.get_pyegeria_platform_config() (EGERIA_VIEW_SERVER_URL /
    # EGERIA_VIEW_SERVER env vars, then config/mcp_servers.json), NOT read from
    # here. egeria_user/egeria_password remain the .env-backed service-account
    # fallback used by advisor.auth.resolve_egeria_credentials() when no
    # per-request session credentials are present.
    egeria_user: str = Field(default="garygeeke", alias="EGERIA_USER")
    egeria_password: str = Field(default="secret", alias="EGERIA_PASSWORD")

    # Comma-separated extra origins allowed to call the API cross-origin, on top of
    # localhost (always allowed for local dev). Needed when this Advisor is embedded
    # in/called from a Portal on a different origin — e.g.
    # "https://egeria.pdr-associates.com". Same-origin browser access (the SPA served
    # from the same host:port as the API) never needs this.
    advisor_extra_cors_origins: str = Field(default="", alias="ADVISOR_EXTRA_CORS_ORIGINS")

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="llama3.1:8b", alias="OLLAMA_MODEL")
    ollama_code_model: str = Field(default="codellama:13b", alias="OLLAMA_CODE_MODEL")
    ollama_temperature: float = Field(default=0.7, alias="OLLAMA_TEMPERATURE")

    # Model tier — see TIER_PRESETS / resolve_llm_tier_config() above.
    # NOTE: the actual resolution logic reads os.environ directly rather
    # than this field, because it needs to distinguish "explicitly set" from
    # "defaulted by pydantic-settings"; this field exists for discoverability
    # (e.g. an admin/health endpoint) and documentation, not as the live
    # source of truth.
    advisor_model_tier: str = Field(default="dev", alias="ADVISOR_MODEL_TIER")

    # Embeddings
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        alias="EMBEDDING_MODEL"
    )
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")

    # MLflow
    # Default matches advisor.yaml observability.mlflow.tracking_uri (the
    # mlflow_tracking_server container listens on 5025). Prefer
    # resolve_mlflow_tracking_uri() over reading this field directly: it
    # applies the env > yaml > default precedence used elsewhere in EA.
    mlflow_tracking_uri: str = Field(
        default=DEFAULT_MLFLOW_TRACKING_URI,
        alias="MLFLOW_TRACKING_URI"
    )
    mlflow_experiment_name: str = Field(
        default="egeria-advisor",
        alias="MLFLOW_EXPERIMENT_NAME"
    )
    mlflow_enable_tracking: bool = Field(default=True, alias="MLFLOW_ENABLE_TRACKING")

    # Phoenix
    phoenix_enable: bool = Field(default=False, alias="PHOENIX_ENABLE")
    phoenix_collector_endpoint: str = Field(
        default="http://localhost:6006",
        alias="PHOENIX_COLLECTOR_ENDPOINT"
    )

    # Advisor
    advisor_data_path: Path = Field(
        default_factory=_egeria_python_path_from_yaml,
        alias="ADVISOR_DATA_PATH"
    )
    advisor_cache_dir: Path = Field(
        default=Path("./data/cache"),
        alias="ADVISOR_CACHE_DIR"
    )
    advisor_log_level: str = Field(default="INFO", alias="ADVISOR_LOG_LEVEL")


def load_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from YAML file.

    Parameters
    ----------
    config_path : Path, optional
        Path to configuration file. If None, uses default location.

    Returns
    -------
    dict
        Configuration dictionary
    """
    if config_path is None:
        config_path = Path(__file__).parent / "configdata" / "advisor.yaml"

    if not config_path.exists():
        logger.warning(f"Config file not found: {config_path}, using defaults")
        return {}

    with open(config_path) as f:
        config = yaml.safe_load(f)

    logger.info(f"Loaded configuration from {config_path}")
    return config


class ResolvedLLMTierConfig(BaseModel):
    """The effective per-tier LLM configuration, after resolving overrides."""
    tier: str
    models: LLMModelConfig
    num_ctx: int
    rag_context_budget_tokens: Optional[int]


def resolve_model_tier(config_path: Optional[Path] = None) -> str:
    """
    Resolve the active model tier.

    Priority: ``ADVISOR_MODEL_TIER`` env var, then ``llm.tier`` in
    advisor.yaml, then the ``dev`` default. An unrecognised value in either
    source is logged and skipped rather than raised, so a typo degrades to
    the default instead of failing startup.
    """
    env_tier = os.environ.get("ADVISOR_MODEL_TIER", "").strip()
    if env_tier:
        if env_tier in TIER_PRESETS:
            return env_tier
        logger.warning(
            f"Unknown ADVISOR_MODEL_TIER={env_tier!r} (expected one of "
            f"{sorted(TIER_PRESETS)}); falling back to llm.tier / default"
        )

    raw = load_config(config_path) or {}
    yaml_tier = (raw.get("llm") or {}).get("tier")
    if yaml_tier:
        if yaml_tier in TIER_PRESETS:
            return yaml_tier
        logger.warning(
            f"Unknown llm.tier={yaml_tier!r} in advisor.yaml (expected one of "
            f"{sorted(TIER_PRESETS)}); falling back to default"
        )

    return DEFAULT_MODEL_TIER


def resolve_mlflow_tracking_uri(config_path: Optional[Path] = None) -> str:
    """
    Resolve the MLflow tracking URI from one source of truth.

    Priority: ``MLFLOW_TRACKING_URI`` env var (checked via ``os.environ``
    directly so an unset var never masquerades as a setting), then
    ``observability.mlflow.tracking_uri`` in advisor.yaml, then
    ``DEFAULT_MLFLOW_TRACKING_URI``.
    """
    env_uri = os.environ.get("MLFLOW_TRACKING_URI", "").strip()
    if env_uri:
        return env_uri

    raw = load_config(config_path) or {}
    yaml_uri = ((raw.get("observability") or {}).get("mlflow") or {}).get("tracking_uri")
    if yaml_uri and str(yaml_uri).strip():
        return str(yaml_uri).strip()

    return DEFAULT_MLFLOW_TRACKING_URI


def resolve_llm_tier_config(config_path: Optional[Path] = None) -> ResolvedLLMTierConfig:
    """
    Resolve the effective per-slot models, ``num_ctx``, and RAG context
    budget for the active tier.

    Per-slot model resolution order (highest wins):
      1. ``OLLAMA_MODEL`` / ``OLLAMA_CODE_MODEL`` env vars, if actually
         present in the environment (checked via ``os.environ`` directly,
         not the AdvisorSettings default, so an unset var never masquerades
         as an override). ``OLLAMA_MODEL`` overrides the query/conversation
         slots; ``OLLAMA_CODE_MODEL`` overrides code/maintenance. Neither
         touches ``planning``, which stays a dedicated slot (see CLAUDE.md
         rule 16) driven only by yaml/tier resolution below.
      2. A slot explicitly present in advisor.yaml's ``llm.models`` block
         (read from the *raw* YAML, so a value that only came from a class
         default never counts as an operator override).
      3. The resolved tier's preset model for that slot.
      4. ``LLMModelConfig``'s own class default (only reachable for ``dev``,
         whose preset leaves models alone).
    """
    tier = resolve_model_tier(config_path)
    preset = TIER_PRESETS[tier]

    raw = load_config(config_path) or {}
    raw_models: Dict[str, Any] = ((raw.get("llm") or {}).get("models")) or {}

    resolved: Dict[str, Any] = LLMModelConfig().model_dump()
    if preset["models"]:
        resolved.update(preset["models"])
    resolved.update({k: v for k, v in raw_models.items() if k in resolved})

    # `planning` is deliberately excluded from OLLAMA_MODEL's scope: it's a
    # dedicated, separately-tuned model slot (see CLAUDE.md rule 16 —
    # get_planning_llm() pins qwen2.5-coder:32b for narrative/refinement
    # quality, independent of the RAG query model). This checkout's own
    # .env sets OLLAMA_MODEL=llama3.1:8b, which was harmless while the alias
    # was dead code — silently downgrading advisor.yaml's chosen planning
    # model the moment the alias started working would be a real regression,
    # not a "keep it working" change.
    ollama_model_env = os.environ.get("OLLAMA_MODEL", "").strip()
    ollama_code_model_env = os.environ.get("OLLAMA_CODE_MODEL", "").strip()
    if ollama_model_env:
        for slot in ("query", "conversation"):
            resolved[slot] = ollama_model_env
    if ollama_code_model_env:
        for slot in ("code", "maintenance"):
            resolved[slot] = ollama_code_model_env

    return ResolvedLLMTierConfig(
        tier=tier,
        models=LLMModelConfig(**resolved),
        num_ctx=preset["num_ctx"],
        rag_context_budget_tokens=preset["rag_context_budget_tokens"],
    )


_llm_tier_config: Optional[ResolvedLLMTierConfig] = None


def get_llm_tier_config(config_path: Optional[Path] = None, force_refresh: bool = False) -> ResolvedLLMTierConfig:
    """Return the cached resolved tier config, logging it once on first resolution."""
    global _llm_tier_config
    if _llm_tier_config is None or force_refresh:
        _llm_tier_config = resolve_llm_tier_config(config_path)
        cfg = _llm_tier_config
        logger.info(
            "LLM tier resolved: tier={} models={} num_ctx={} rag_context_budget_tokens={}".format(
                cfg.tier, cfg.models.model_dump(), cfg.num_ctx, cfg.rag_context_budget_tokens
            )
        )
    return _llm_tier_config


def get_full_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Get full configuration including all nested configs.

    Parameters
    ----------
    config_path : Path, optional
        Path to configuration file

    Returns
    -------
    dict
        Full configuration with all sections
    """
    config = load_config(config_path)

    # Parse nested configurations
    full_config = {
        "data_sources": DataSourceConfig(**config.get("data_sources", {})),
        "vector_store": VectorStoreConfig(**config.get("vector_store", {})),
        "pgvector": PgVectorConfig(**config.get("pgvector", {})),
        "llm": LLMConfig(**config.get("llm", {})),
        "embeddings": EmbeddingConfig(**config.get("embeddings", {})),
        "rag": RAGConfig(**config.get("rag", {})),
        "agents": AgentsConfig(**config.get("agents", {})),
        "cli": CLIConfig(**config.get("cli", {})),
        "observability": ObservabilityConfig(**config.get("observability", {})),
        "logging": LoggingConfig(**config.get("logging", {})),
    }

    # Apply the resolved model tier on top of the yaml-parsed llm/rag blocks:
    # per-slot models, num_ctx, and the RAG context token budget. See
    # resolve_llm_tier_config()'s docstring for the override precedence.
    tier_cfg = get_llm_tier_config(config_path)
    full_config["llm"].tier = tier_cfg.tier
    full_config["llm"].models = tier_cfg.models
    full_config["llm"].num_ctx = tier_cfg.num_ctx
    full_config["rag"].context.budget_tokens = tier_cfg.rag_context_budget_tokens

    return full_config


# Global settings instance
try:
    settings = AdvisorSettings()
    logger.info("Settings loaded successfully")
except Exception as e:
    logger.warning(f"Could not load settings from environment: {e}")
    logger.info("Using default settings")
    settings = AdvisorSettings()


__all__ = [
    "settings",
    "load_config",
    "get_full_config",
    "DEFAULT_MODEL_TIER",
    "TIER_PRESETS",
    "ResolvedLLMTierConfig",
    "resolve_model_tier",
    "resolve_llm_tier_config",
    "get_llm_tier_config",
    "DataSourceConfig",
    "VectorStoreConfig",
    "PgVectorConfig",
    "LLMConfig",
    "EmbeddingConfig",
    "RAGConfig",
    "RAGRetrievalConfig",
    "RAGContextConfig",
    "RAGGenerationConfig",
    "AgentsConfig",
    "CLIConfig",
    "ObservabilityConfig",
    "LoggingConfig",
]
