from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPACE_DIR = ROOT / "hf_space_bundle"


def load_env_file(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    include_images = os.getenv("HF_INCLUDE_IMAGES", "1") == "1"
    patterns = [".venv", "__pycache__", "*.pyc", "*.log"]
    if not include_images:
        patterns.extend(["*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.bmp", "*.svg"])
    ignore = shutil.ignore_patterns(*patterns)
    shutil.copytree(src, dst, ignore=ignore)


def prepare_bundle() -> None:
    if SPACE_DIR.exists():
        shutil.rmtree(SPACE_DIR)
    SPACE_DIR.mkdir(parents=True)

    shutil.copy2(ROOT / "rag_chatbot" / "app.py", SPACE_DIR / "app.py")
    shutil.copy2(ROOT / "rag_chatbot" / "README.md", SPACE_DIR / "README.md")
    copytree(ROOT / "rag_chatbot" / "web", SPACE_DIR / "web")
    copytree(ROOT / "organized_maintenance_docs_simple", SPACE_DIR / "organized_maintenance_docs_simple")

    base_requirements = (ROOT / "rag_chatbot" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    llm_requirements = (ROOT / "rag_chatbot" / "requirements-llm.txt").read_text(encoding="utf-8").splitlines()
    requirements = [line for line in base_requirements + llm_requirements if line.strip()]
    (SPACE_DIR / "requirements.txt").write_text("\n".join(requirements) + "\n", encoding="utf-8")

    readme = SPACE_DIR / "README.md"
    text = readme.read_text(encoding="utf-8")
    if "sdk: gradio" not in text:
        text = "---\ntitle: HK Maintenance RAG Chatbot\nsdk: gradio\napp_file: app.py\npinned: false\n---\n\n" + text
    readme.write_text(text, encoding="utf-8", newline="\n")


def deploy_bundle() -> None:
    token = os.getenv("HF_TOKEN")
    space_id = os.getenv("HF_SPACE_ID")
    if not token:
        raise SystemExit("HF_TOKEN 환경 변수가 없습니다.")
    if not space_id:
        raise SystemExit("HF_SPACE_ID 환경 변수가 없습니다. 예: username/hk-maintenance-rag")

    supabase_db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL", "")
    if supabase_db_url:
        print(
            "\n[경고] 로컬에 SUPABASE_DB_URL이 설정되어 있습니다.\n"
            "HuggingFace Space에도 동일한 값을 시크릿으로 등록하지 않으면\n"
            "Space는 파일 모드로 동작하여 Supabase에서 삭제한 내용이 반영되지 않습니다.\n"
            f"  → https://huggingface.co/spaces/{space_id}/settings 에서\n"
            "     SUPABASE_DB_URL 시크릿을 추가하세요.\n"
            "     초기 씨딩이 이미 완료된 경우 SUPABASE_SEED_FROM_FILES=0 도 함께 설정하세요.\n"
        )

    from huggingface_hub import HfApi, create_repo

    create_repo(
        repo_id=space_id,
        repo_type="space",
        space_sdk="gradio",
        private=True,
        token=token,
        exist_ok=True,
    )
    api = HfApi(token=token)
    api.upload_folder(
        folder_path=str(SPACE_DIR),
        repo_id=space_id,
        repo_type="space",
        commit_message="Deploy HK maintenance RAG chatbot",
    )
    print(f"deployed=https://huggingface.co/spaces/{space_id}")


def main() -> None:
    load_env_file()
    prepare_bundle()
    print(f"prepared={SPACE_DIR}")
    if os.getenv("HF_DEPLOY", "0") == "1":
        deploy_bundle()
    else:
        print("HF_DEPLOY=1, HF_TOKEN, HF_SPACE_ID를 설정하면 업로드까지 진행합니다.")


if __name__ == "__main__":
    main()
