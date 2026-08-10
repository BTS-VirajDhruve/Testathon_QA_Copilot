"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ (parent of app/) — stable regardless of process cwd
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BACKEND_ROOT / ".env"), ".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    api_host: str = "localhost"
    api_port: int = 8000
    uvicorn_reload: bool = True
    uvicorn_workers: int = 1
    uvicorn_log_level: str = "info"
    uvicorn_proxy_headers: bool = True
    uvicorn_forwarded_allow_ips: str = "*"
    uvicorn_timeout_keep_alive_seconds: int = 10
    uvicorn_timeout_graceful_shutdown_seconds: int = 30
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    log_level: str = "INFO"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    # Task-aware routing (empty = use DEFAULT_TASK_MODEL_MAP / OPENAI_MODEL)
    openai_model_intent_classification: str = ""
    openai_model_qa_documentation: str = ""
    openai_model_regression_selection: str = ""
    openai_model_bug_report: str = ""
    openai_model_test_case_generation: str = ""
    openai_model_targeted_test_generation: str = ""
    openai_model_exploratory_scenario: str = ""
    openai_model_reviewer_pass: str = ""
    openai_model_graph_extraction: str = ""
    openai_model_entity_extraction: str = ""
    openai_model_output_repair: str = ""
    openai_model_critic_notes: str = ""
    openai_model_test_review_automation: str = ""
    openai_model_test_validity_review: str = ""
    openai_model_automation_feasibility_review: str = ""
    openai_model_bdd_export_conversion: str = ""
    openai_model_escalation_target: str = ""

    # BDD export
    bdd_export_max_background_steps: int = 4

    # Iterative test refinement / coverage closure
    test_refinement_enabled: bool = True
    test_refinement_max_iterations: int = 6
    test_refinement_max_tests: int = 250
    test_refinement_min_improvement_percent: float = 1.0
    test_refinement_stagnation_rounds: int = 2
    test_refinement_max_llm_calls: int = 12
    test_refinement_require_all_mandatory: bool = True
    test_refinement_require_zero_invalid: bool = True
    test_refinement_require_zero_needs_revision: bool = True

    # Initial / targeted generation volume
    test_generation_min_cases: int = 25
    test_generation_max_per_gap: int = 3
    test_generation_max_gaps_per_round: int = 8
    test_generation_max_regeneration_rounds: int = 2

    # Atlassian Cloud (Jira + Confluence) — OAuth 2.0 3LO.
    # Secrets stay backend-only.
    atlassian_integration_enabled: bool = True
    atlassian_oauth_client_id: str = ""
    atlassian_oauth_client_secret: str = ""
    atlassian_oauth_redirect_uri: str = (
        "http://localhost:8000/api/integrations/atlassian/callback"
    )
    atlassian_oauth_scopes: str = (
        "read:jira-work read:space:confluence "
        "read:page:confluence offline_access"
    )
    atlassian_token_encryption_key: str = ""
    atlassian_request_timeout_seconds: float = 30.0
    atlassian_max_retries: int = 3
    atlassian_default_page_size: int = 50
    atlassian_import_max_items: int = 200
    atlassian_comments_import_enabled: bool = False
    atlassian_attachments_import_enabled: bool = False
    atlassian_frontend_base_url: str = "http://localhost:3000"

    # Feature flags
    model_routing_enabled: bool = True
    model_escalation_enabled: bool = True
    model_reviewer_enabled: bool = False
    model_routing_log_enabled: bool = True
    # Comma list of LLMTaskType values, or * / all / empty for all tasks
    model_routing_enabled_tasks: str = "*"

    model_escalate_on_security: bool = True
    model_escalate_on_release_blocking: bool = True
    model_escalate_on_financial: bool = True
    model_escalate_on_validation_failure: bool = True
    model_escalate_on_ambiguity: bool = True

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_enabled: bool = False

    # MongoDB
    mongo_enabled: bool = True
    mongo_required: bool = False
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "qa_copilot"
    mongo_connect_timeout_ms: int = 1500

    # Auth / JWT
    jwt_issuer: str = "agentic-qa-copilot"
    jwt_access_secret: str = "change-me-access-secret"
    jwt_refresh_secret: str = "change-me-refresh-secret"
    jwt_access_token_minutes: int = 30
    jwt_refresh_token_days: int = 14
    forgot_password_token_expire_minutes: int = 30
    invite_token_expire_minutes: int = 1440

    # Frontend link base (for auth emails)
    frontend_base_url: str = "http://localhost:3000"

    # AWS SES
    aws_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_ses_from_email: str = ""
    aws_ses_from_name: str = "QA Copilot"

    # Relative paths resolve against BACKEND_ROOT (not process cwd).
    data_dir: str = "./data"
    chroma_dir: str = "./data/chroma"
    chroma_tenant: str = "default_tenant"
    chroma_database: str = "qa_copilot_chroma"
    chroma_use_http: bool = False
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_ssl: bool = False
    chroma_collection: str = "qa_copilot_docs"
    enable_demo_fallback: bool = True

    @model_validator(mode="after")
    def _resolve_data_paths(self) -> "Settings":
        backend_root = BACKEND_ROOT.resolve()
        for field in ("data_dir", "chroma_dir"):
            raw = getattr(self, field)
            path = Path(raw)
            if not path.is_absolute():
                resolved = (BACKEND_ROOT / path).resolve()
            else:
                resolved = path.resolve()
            if field == "chroma_dir":
                try:
                    resolved.relative_to(backend_root)
                except ValueError as exc:
                    raise ValueError(
                        "chroma_dir must stay inside backend project directory",
                    ) from exc
            setattr(self, field, str(resolved))
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env.strip().lower() == "development"

    @property
    def effective_uvicorn_reload(self) -> bool:
        return self.is_development and self.uvicorn_reload

    @property
    def effective_uvicorn_workers(self) -> int:
        # Uvicorn cannot run multiple workers with auto-reload enabled.
        if self.effective_uvicorn_reload:
            return 1
        return max(1, self.uvicorn_workers)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.strip())

    @property
    def atlassian_oauth_configured(self) -> bool:
        return bool(
            self.atlassian_oauth_client_id.strip()
            and self.atlassian_oauth_client_secret.strip()
        )

    @property
    def atlassian_scope_list(self) -> list[str]:
        return [
            s.strip()
            for s in self.atlassian_oauth_scopes.replace(",", " ").split()
            if s.strip()
        ]

    @property
    def atlassian_data_dir(self) -> Path:
        return Path(self.data_dir) / "atlassian"

    @model_validator(mode="after")
    def _validate_runtime_hardening(self) -> "Settings":
        insecure_secrets = {
            "change-me-access-secret",
            "change-me-refresh-secret",
            "",
        }
        if self.mongo_required and not self.mongo_enabled:
            raise ValueError("mongo_required=true requires mongo_enabled=true")
        if not self.is_development:
            if self.jwt_access_secret.strip() in insecure_secrets:
                raise ValueError(
                    "jwt_access_secret must be secure outside development",
                )
            if self.jwt_refresh_secret.strip() in insecure_secrets:
                raise ValueError(
                    "jwt_refresh_secret must be secure outside development",
                )
            if "*" in self.cors_origin_list:
                raise ValueError(
                    "Wildcard CORS origin is not allowed outside development"
                )
        return self

    def ensure_dirs(self) -> None:
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.chroma_dir).mkdir(parents=True, exist_ok=True)
        self.atlassian_data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
