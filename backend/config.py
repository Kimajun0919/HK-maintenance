from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR.parent / ".env", override=False)
load_dotenv(APP_DIR / ".env", override=False)

DEFAULT_DOCS_DIR = APP_DIR / "organized_maintenance_docs_simple"
if not DEFAULT_DOCS_DIR.exists():
    DEFAULT_DOCS_DIR = APP_DIR.parent / "organized_maintenance_docs_simple"

DOCS_DIR = Path(os.getenv("DOCS_DIR", DEFAULT_DOCS_DIR)).resolve()
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "512"))
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
DOC_STORAGE = os.getenv("DOC_STORAGE", "supabase" if SUPABASE_DB_URL else "files").strip().lower()
SUPABASE_ENABLED = DOC_STORAGE == "supabase" and bool(SUPABASE_DB_URL)
SUPABASE_AUTO_MIGRATE = os.getenv("SUPABASE_AUTO_MIGRATE", "1") != "0"
SUPABASE_SEED_FROM_FILES = os.getenv("SUPABASE_SEED_FROM_FILES", "1") != "0"
ASSET_MAX_SIZE_MB = float(os.getenv("ASSET_MAX_SIZE_MB", "2"))
ASSET_MAX_SIZE_BYTES = int(ASSET_MAX_SIZE_MB * 1024 * 1024)
SUPABASE_DOCS_TABLE = os.getenv("SUPABASE_DOCS_TABLE", "maintenance_docs")
SUPABASE_ASSETS_TABLE = os.getenv("SUPABASE_ASSETS_TABLE", f"{SUPABASE_DOCS_TABLE}_assets")
SUPABASE_FOLDERS_TABLE = os.getenv("SUPABASE_FOLDERS_TABLE", f"{SUPABASE_DOCS_TABLE}_folders")
SUPABASE_META_TABLE = f"{SUPABASE_DOCS_TABLE}_meta"

for table_name, env_name in (
    (SUPABASE_DOCS_TABLE, "SUPABASE_DOCS_TABLE"),
    (SUPABASE_ASSETS_TABLE, "SUPABASE_ASSETS_TABLE"),
    (SUPABASE_FOLDERS_TABLE, "SUPABASE_FOLDERS_TABLE"),
):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
        raise ValueError(f"{env_name} must be a simple SQL identifier")
