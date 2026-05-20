from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR.parent / ".env", override=False)
load_dotenv(APP_DIR / ".env", override=False)


SUPABASE_PROFILE = os.getenv("SUPABASE_PROFILE", "").strip()


def _profile_suffix(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()


SUPABASE_PROFILE_SUFFIX = _profile_suffix(SUPABASE_PROFILE)
SUPABASE_PROFILE_STRICT = os.getenv("SUPABASE_PROFILE_STRICT", "1" if SUPABASE_PROFILE_SUFFIX else "0") != "0"


def _profiled_env(name: str, default: str = "", strict: bool = False) -> str:
    if SUPABASE_PROFILE_SUFFIX:
        profiled_name = f"{name}_{SUPABASE_PROFILE_SUFFIX}"
        profiled_value = os.getenv(profiled_name)
        if profiled_value is not None and profiled_value != "":
            return profiled_value
        if strict:
            return default
    return os.getenv(name, default)

DEFAULT_DOCS_DIR = APP_DIR / "organized_maintenance_docs_simple"
if not DEFAULT_DOCS_DIR.exists():
    DEFAULT_DOCS_DIR = APP_DIR.parent / "organized_maintenance_docs_simple"

DOCS_DIR = Path(os.getenv("DOCS_DIR", DEFAULT_DOCS_DIR)).resolve()
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
USE_LLM = os.getenv("USE_LLM", "0") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "512"))
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
SUPABASE_DB_URL = _profiled_env("SUPABASE_DB_URL", strict=SUPABASE_PROFILE_STRICT) or _profiled_env("DATABASE_URL", strict=SUPABASE_PROFILE_STRICT)
DOC_STORAGE = _profiled_env("DOC_STORAGE", "supabase" if SUPABASE_DB_URL else "files").strip().lower()
SUPABASE_ENABLED = DOC_STORAGE == "supabase" and bool(SUPABASE_DB_URL)
SUPABASE_AUTO_MIGRATE = _profiled_env("SUPABASE_AUTO_MIGRATE", "1") != "0"
SUPABASE_SEED_FROM_FILES = _profiled_env("SUPABASE_SEED_FROM_FILES", "1") != "0"
ASSET_MAX_SIZE_MB = float(os.getenv("ASSET_MAX_SIZE_MB", "2"))
ASSET_MAX_SIZE_BYTES = int(ASSET_MAX_SIZE_MB * 1024 * 1024)
APP_HOST = os.getenv("APP_HOST", "127.0.0.1").strip() or "127.0.0.1"
APP_PORT = int(os.getenv("APP_PORT", "7860"))
APP_ALLOW_REMOTE_FOLDER_PARSE = os.getenv("APP_ALLOW_REMOTE_FOLDER_PARSE", "0") == "1"
SUPABASE_DOCS_TABLE = _profiled_env("SUPABASE_DOCS_TABLE", "maintenance_docs")
SUPABASE_ASSETS_TABLE = _profiled_env("SUPABASE_ASSETS_TABLE", f"{SUPABASE_DOCS_TABLE}_assets")
SUPABASE_FOLDERS_TABLE = _profiled_env("SUPABASE_FOLDERS_TABLE", f"{SUPABASE_DOCS_TABLE}_folders")
SUPABASE_CHUNKS_TABLE = _profiled_env("SUPABASE_CHUNKS_TABLE", f"{SUPABASE_DOCS_TABLE}_chunks")
SUPABASE_META_TABLE = _profiled_env("SUPABASE_META_TABLE", f"{SUPABASE_DOCS_TABLE}_meta")
SUPABASE_REQUESTS_TABLE = _profiled_env("SUPABASE_REQUESTS_TABLE", "maintenance_requests")
SUPABASE_REQUEST_IMPORTS_TABLE = _profiled_env("SUPABASE_REQUEST_IMPORTS_TABLE", f"{SUPABASE_REQUESTS_TABLE}_imports")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
RAG_ENABLE_NGRAM_INDEX = os.getenv("RAG_ENABLE_NGRAM_INDEX", "1") != "0"
RAG_ENABLE_LEGACY_INDEX = os.getenv("RAG_ENABLE_LEGACY_INDEX", "1") != "0"

for table_name, env_name in (
    (SUPABASE_DOCS_TABLE, "SUPABASE_DOCS_TABLE"),
    (SUPABASE_ASSETS_TABLE, "SUPABASE_ASSETS_TABLE"),
    (SUPABASE_FOLDERS_TABLE, "SUPABASE_FOLDERS_TABLE"),
    (SUPABASE_CHUNKS_TABLE, "SUPABASE_CHUNKS_TABLE"),
    (SUPABASE_META_TABLE, "SUPABASE_META_TABLE"),
    (SUPABASE_REQUESTS_TABLE, "SUPABASE_REQUESTS_TABLE"),
    (SUPABASE_REQUEST_IMPORTS_TABLE, "SUPABASE_REQUEST_IMPORTS_TABLE"),
):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"{env_name} must be a simple SQL identifier")
