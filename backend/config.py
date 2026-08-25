"""Application configuration settings."""

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
class Settings(BaseSettings):
    """Global configuration settings for LoL Remote Pick."""

    # Server settings
    host: str = Field(default="0.0.0.0", description="Backend server host")
    port: int = Field(default=8000, description="Backend server port")
    cors_origins: List[str] = Field(default=["*"], description="Allowed CORS origins")

    # Mode & polling
    mock_mode: bool = Field(default=False, description="Run in mock LCU simulation mode")
    lcu_poll_interval: float = Field(default=2.0, description="Interval in seconds for polling LCU status")

    # Data Dragon & assets
    ddragon_version: str = Field(default="14.20.1", description="Default DataDragon version for assets")
    static_dir: Optional[str] = Field(default=None, description="Path to frontend static build directory")

    # Mock LCU settings
    mock_port: int = Field(default=8888, description="Mock LCU server HTTP port")
    mock_ws_port: int = Field(default=8888, description="Mock LCU server WebSocket port")
    mock_auto_progress: bool = Field(default=True, description="Automatically progress mock phases with timers")

    # Optional custom path for League of Legends lockfile / install
    custom_league_path: Optional[str] = Field(default=None, description="Custom path to LoL installation or lockfile")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_static_path(self) -> Path:
        """Resolve frontend static directory path, supporting dev and frozen PyInstaller bundles."""
        if self.static_dir:
            return Path(self.static_dir).resolve()

        # Check PyInstaller frozen bundle location
        if getattr(sys, "frozen", False):
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                meipass_p = Path(meipass) / "frontend"
                if meipass_p.is_dir():
                    return meipass_p
            exe_dir = Path(sys.executable).parent / "frontend"
            if exe_dir.is_dir():
                return exe_dir

        # Default fallback to frontend/dist or frontend relative to project root
        base_dir = Path(__file__).resolve().parent.parent
        frontend_dist = base_dir / "frontend" / "dist"
        if frontend_dist.is_dir():
            return frontend_dist
        frontend_dir = base_dir / "frontend"
        return frontend_dir

@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


# Default instance
settings = get_settings()
