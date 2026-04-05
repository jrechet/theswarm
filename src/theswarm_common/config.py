"""Configuration — shared base classes and YAML + env var loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MattermostConfig(BaseModel):
    base_url: str = ""
    bot_token: str = ""
    channel_name: str = "swarm-bots-logs"


class OllamaConfig(BaseModel):
    base_url: str = "http://host.docker.internal:11434"
    model: str = "mistral:7b"
    timeout: int = 300


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8090
    external_url: str = ""

    @field_validator("external_url")
    @classmethod
    def _validate_external_url(cls, v: str) -> str:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("external_url must start with http:// or https://")
        return v


def load_yaml_with_env(config_path: str | Path = "theswarm.yaml") -> dict:
    """Load YAML config and inject common env vars. Returns raw dict for subclass parsing."""
    from dotenv import load_dotenv
    load_dotenv()

    config_path = Path(config_path)
    yaml_data: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Inject common secrets from env vars
    if token := os.getenv("MATTERMOST_BOT_TOKEN"):
        yaml_data.setdefault("mattermost", {})["bot_token"] = token
    if url := os.getenv("OLLAMA_BASE_URL"):
        yaml_data.setdefault("ollama", {})["base_url"] = url
    if ext_url := os.getenv("EXTERNAL_URL"):
        yaml_data.setdefault("server", {})["external_url"] = ext_url

    return yaml_data
