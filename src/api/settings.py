"""The single env-backed settings object, read ONCE at the composition root (PLAN.md §5).

Services never read the environment: they receive these values by injection. App variables
use the AUDIO_SEARCH_ prefix; HF_TOKEN is unprefixed because huggingface_hub reads it by that name.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from domain.errors import ConfigurationError
from domain.models import Branch

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AUDIO_SEARCH_",
        env_file=REPO_ROOT / ".env",
        # .env also holds variables for features outside this build (e.g. the gated answer-
        # generation stretch item); they are deliberately not read.
        extra="ignore",
    )

    database_url: str
    hf_token: str | None = Field(default=None, validation_alias=AliasChoices("HF_TOKEN", "AUDIO_SEARCH_HF_TOKEN"))

    whisper_model: str = "large-v3-turbo"
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- the five configurable values (PLAN.md §5, §17) ---
    rrf_k: int = Field(default=60, gt=0)
    # Equal weights are the permanent measured baseline (§7); change only with a recorded before/after.
    fusion_weight_keyword: float = Field(default=1.0, ge=0.0, allow_inf_nan=False)
    fusion_weight_semantic: float = Field(default=1.0, ge=0.0, allow_inf_nan=False)
    # Default is decided and recorded in Task 5; until then it must be set explicitly to search.
    candidate_depth_multiplier: int | None = Field(default=None, ge=1)
    hnsw_ef_search: int = Field(default=40, ge=1)
    split_soft_min_seconds: float = Field(default=20.0, gt=0)
    split_cap_seconds: float = Field(default=45.0, gt=0)

    log_level: str = "INFO"

    @field_validator("candidate_depth_multiplier", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("log_level")
    @classmethod
    def _known_level(cls, value: str) -> str:
        level = value.upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level {value!r}")
        return level

    @model_validator(mode="after")
    def _split_window_is_ordered(self) -> Settings:
        if self.split_soft_min_seconds >= self.split_cap_seconds:
            raise ValueError(
                f"split_soft_min_seconds ({self.split_soft_min_seconds}) must be < split_cap_seconds ({self.split_cap_seconds})"
            )
        return self

    @property
    def fusion_weights(self) -> dict[Branch, float]:
        return {Branch.KEYWORD: self.fusion_weight_keyword, Branch.SEMANTIC: self.fusion_weight_semantic}


def load_settings(**overrides: object) -> Settings:
    """Load and validate once. Invalid config becomes a typed ConfigurationError, never a silent default."""
    try:
        settings = Settings(**overrides)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'settings'}: {err['msg']}" for err in e.errors())
        raise ConfigurationError(f"invalid configuration: {problems}", stage="config") from e
    for branch, weight in settings.fusion_weights.items():
        if weight == 0.0:
            log.warning("fusion weight is 0.0: branch disabled (diagnostic use only)", extra={"branch": branch.value})
    return settings
