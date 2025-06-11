import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class SlackConfig(BaseSettings):
    """Configuration for Slack workspace migration"""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )

    # Source workspace configuration
    source_token: str = Field(..., alias="SOURCE_SLACK_TOKEN")
    source_workspace_name: Optional[str] = Field(None, alias="SOURCE_WORKSPACE_NAME")

    # Destination workspace configuration
    dest_token: str = Field(..., alias="DEST_SLACK_TOKEN")
    dest_workspace_name: Optional[str] = Field(None, alias="DEST_WORKSPACE_NAME")

    # Migration settings
    batch_size: int = Field(100, alias="BATCH_SIZE")
    rate_limit_delay: float = Field(1.0, alias="RATE_LIMIT_DELAY")
    max_retries: int = Field(3, alias="MAX_RETRIES")

    # Output settings
    output_dir: str = Field("migration_data", alias="OUTPUT_DIR")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

def get_config() -> SlackConfig:
    """Get configuration instance"""
    return SlackConfig()
