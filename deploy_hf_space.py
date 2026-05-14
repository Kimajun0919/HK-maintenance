from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPACE_DIR = ROOT / "hf_space_bundle"


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", "*.log")
    shutil.copytree(src, dst, ignore=ignore)


def prepare_bundle() -> None:
    if SPACE_DIR.exists():
        shutil.rmtree(SPACE_DIR)
    SPACE_DIR.mkdir(parents=True)

    shutil.copy2(ROOT / "rag_chatbot" / "app.py", SPACE_DIR / "app.py")
    shutil.copy2(ROOT / "rag_chatbot" / "README.md", SPACE_DIR / "README.md")
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
    prepare_bundle()
    print(f"prepared={SPACE_DIR}")
    if os.getenv("HF_DEPLOY", "0") == "1":
        deploy_bundle()
    else:
        print("HF_DEPLOY=1, HF_TOKEN, HF_SPACE_ID를 설정하면 업로드까지 진행합니다.")


if __name__ == "__main__":
    main()
