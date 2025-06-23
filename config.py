import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class SlackConfig:
    """Configuration for Slack migration"""
    source_token: str
    dest_token: str
    source_user_token: Optional[str]  # User token for operations requiring user permissions
    source_workspace_name: Optional[str] = None
    dest_workspace_name: Optional[str] = None
    batch_size: int = 100
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    output_dir: str = "migration_data"
    log_level: str = "INFO"

def get_config() -> SlackConfig:
    """Get configuration from environment variables"""

    # Required tokens
    source_token = os.getenv("SOURCE_SLACK_TOKEN")
    dest_token = os.getenv("DEST_SLACK_TOKEN")

    if not source_token:
        raise ValueError("SOURCE_SLACK_TOKEN environment variable is required")
    if not dest_token:
        raise ValueError("DEST_SLACK_TOKEN environment variable is required")

    # Optional user token for operations requiring user permissions (like unarchiving)
    source_user_token = os.getenv("SOURCE_USER_TOKEN")

    return SlackConfig(
        source_token=source_token,
        dest_token=dest_token,
        source_user_token=source_user_token,
        source_workspace_name=os.getenv("SOURCE_WORKSPACE_NAME"),
        dest_workspace_name=os.getenv("DEST_WORKSPACE_NAME"),
        batch_size=int(os.getenv("BATCH_SIZE", "100")),
        rate_limit_delay=float(os.getenv("RATE_LIMIT_DELAY", "1.0")),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        output_dir=os.getenv("OUTPUT_DIR", "migration_data"),
        log_level=os.getenv("LOG_LEVEL", "INFO")
    )
