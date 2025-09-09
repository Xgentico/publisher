# config.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field, ValidationError

# Load .env only in local/dev; on Render you'll set env vars in the dashboard.
try:
    from dotenv import load_dotenv
    # If a .env exists alongside this file, load it. Safe if file missing.
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()  # fallback: load from CWD if present
except Exception:
    pass  # don't block if dotenv isn't available

def _env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    val = os.getenv(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val

# ---- NEW small helpers for DB URL handling ----
def _normalize(url: str) -> str:
    """Ensure SQLAlchemy-friendly scheme."""
    return url.replace("postgres://", "postgresql+psycopg2://", 1) if url and url.startswith("postgres://") else url

def _with_sslmode(url: str, sslmode: str = "require") -> str:
    """Append sslmode param if not present."""
    if not url:
        return url
    return url if "sslmode=" in url else f"{url}{'&' if '?' in url else '?'}sslmode={sslmode}"

class Settings(BaseModel):
    # Project paths
    project_root: Path = Path(__file__).resolve().parent
    brand_prompt_path: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "prompts" / "prompt.txt")
    input_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "data" / "inputs")
    output_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "data" / "outputs")
    artifacts_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "data" / "outputs" / "artifacts")

    # Policy knobs
    min_citations_per_section: int = 3
    max_similarity_ratio: float = 0.22  # 22% heuristic
    domain_topic: str = "neuroscience"
    open_access_only: bool = True

    # ==== Secrets / External services ====
    # OpenAI
    openai_api_key: str = Field(default_factory=lambda: _env("OPENAI_API_KEY", required=True))
    openai_model: str = Field(default_factory=lambda: _env("OPENAI_MODEL", default="gpt-4o-mini"))

    # PostgreSQL (legacy pieces still supported as fallback)
    pg_db: Optional[str] = Field(default_factory=lambda: _env("POSTGRES_DB"))
    pg_user: Optional[str] = Field(default_factory=lambda: _env("POSTGRES_USER"))
    pg_password: Optional[str] = Field(default_factory=lambda: _env("POSTGRES_PASSWORD"))
    pg_host: Optional[str] = Field(default_factory=lambda: _env("POSTGRES_HOST", default="localhost"))
    pg_port: Optional[str] = Field(default_factory=lambda: _env("POSTGRES_PORT", default="5432"))
    pg_sslmode: Optional[str] = Field(default_factory=lambda: _env("DB_SSLMODE", default="disable"))

    # Qdrant
    qdrant_api_key: Optional[str] = Field(default_factory=lambda: _env("QDRANT_API_KEY"))
    qdrant_url: Optional[str] = Field(default_factory=lambda: _env("QDRANT_URL"))

    # Optional: Google Drive uploader (later)
    google_service_account_json_b64: Optional[str] = Field(default_factory=lambda: _env("GOOGLE_SA_JSON_B64"))

    @property
    def postgres_url(self) -> Optional[str]:
        """
        Preferred: DATABASE_URL from env (Render “External Database URL”).
        Fallback: build from POSTGRES_* vars. Always ensure proper driver and sslmode.
        """
        # 1) Prefer single DATABASE_URL
        db_url = (os.getenv("DATABASE_URL") or "").strip()
        if db_url:
            return _with_sslmode(_normalize(db_url), "require")

        # 2) Fallback to individual POSTGRES_* vars
        if all([self.pg_db, self.pg_user, self.pg_password, self.pg_host, self.pg_port]):
            url = (
                f"postgresql+psycopg2://{self.pg_user}:{self.pg_password}"
                f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
            )
            return _with_sslmode(url, self.pg_sslmode or "require")

        return None

settings = Settings()
settings.artifacts_dir.mkdir(parents=True, exist_ok=True)

# ---- Convenience helpers (optional) ----
def require_key(name: str, value: Optional[str]):
    if not value:
        raise RuntimeError(f"{name} is required but not set. Provide it via .env or Render env settings.")

def get_openai_client():
    """Return an OpenAI client configured from env. Keeps all services centralized here."""
    require_key("OPENAI_API_KEY", settings.openai_api_key)
    # Using official OpenAI SDK v1.x style:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai>=1.0.0 package is required. pip install openai") from e
    return OpenAI(api_key=settings.openai_api_key)

def get_qdrant_client():
    """Return a Qdrant client if configured; otherwise None."""
    if not (settings.qdrant_api_key and settings.qdrant_url):
        return None
    try:
        from qdrant_client import QdrantClient
    except ImportError as e:
        raise RuntimeError("qdrant-client package is required for Qdrant integration.") from e
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        prefer_grpc=False
    )
