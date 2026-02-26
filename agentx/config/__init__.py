"""Configuration module for agentx."""

from agentx.config.loader import load_config, get_config_path
from agentx.config.schema import Config

__all__ = ["Config", "load_config", "get_config_path"]
