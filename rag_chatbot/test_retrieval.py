from __future__ import annotations

import os

os.environ.setdefault("USE_LLM", "0")

import app


def main() -> None:
    question = "대한항공 VPN 접속 방법 알려줘"
    print(f"DOCS_DIR={app.DOCS_DIR}")
    print(f"chunks={len(app.chunks)}")
    print(f"question={question}")
    print("=" * 80)
    print(app.answer(question, top_k=5))


if __name__ == "__main__":
    main()
