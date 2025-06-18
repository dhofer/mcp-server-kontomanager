# mcp-server-kontomanager/src/mcp_server_kontomanager/settings.py

import logging
import sys
from typing import Dict

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Holds the configuration for the Kontomanager client.
    Values are loaded from environment variables or a .env file.
    """
    # Configure pydantic-settings to look for a .env file and use a prefix
    model_config = SettingsConfigDict(
        env_prefix='KONTOMANAGER_',
        env_file='.env',
        env_file_encoding='utf-8',
        extra='ignore'  # Ignore extra fields from .env file
    )

    brand: str = Field(..., description="The brand to use (e.g., 'yesss', 'georg', 'xoxo').")
    username: str = Field(..., description="The phone number used for login.")
    password: str = Field(..., description="The password for the Kontomanager account.")

    @property
    def base_url(self) -> str:
        """
        Returns the base URL for the selected brand.
        """
        brand_urls: Dict[str, str] = {
            "yesss": "https://www.yesss.at/kontomanager.at/app/",
            "georg": "https://kundencenter.georg.at/app/",
            "xoxo": "https://xoxo.kontomanager.at/app/",
        }
        if self.brand.lower() not in brand_urls:
            raise ValueError(f"Unknown brand: {self.brand}. Supported brands are: {', '.join(brand_urls.keys())}")
        return brand_urls[self.brand.lower()]

# Create a single settings instance to be used throughout the application.
# If required settings are missing, this will now print a helpful error message and exit.
try:
    settings = Settings()
except ValidationError as e:
    error_messages = [
        "--- CONFIGURATION ERROR ---",
        "The MCP server cannot start because the following required settings are missing:",
        "",
    ]
    for error in e.errors():
        var_name = f"KONTOMANAGER_{error['loc'][0].upper()}"
        error_messages.append(f"  - Variable '{var_name}' is missing.")

    error_messages.extend([
        "",
        "Please provide these settings in one of two ways:",
        "1. As environment variables (e.g., export KONTOMANAGER_BRAND=yesss)",
        "2. In a '.env' file in your project's root directory.",
        "",
        "Example '.env' file:",
        "-----------------------------------------",
        "KONTOMANAGER_BRAND=yesss",
        "KONTOMANAGER_USERNAME=your_phone_number",
        "KONTOMANAGER_PASSWORD=your_password",
        "-----------------------------------------",
        ""
    ])

    # Log the friendly error message and exit the application
    logger.critical("\n".join(error_messages))
    sys.exit(1)
