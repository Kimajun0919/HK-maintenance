from __future__ import annotations

import os
import re
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DOCS_DIR = APP_DIR / "organized_maintenance_docs_simple"
if not DEFAULT_DOCS_DIR.exists():
    DEFAULT_DOCS_DIR = APP_DIR.parent / "organized_maintenance_docs_simple"
DOCS_DIR = Path(os.getenv("DOCS_DIR", DEFAULT_DOCS_DIR)).resolve()
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "HuggingFaceTB/SmolLM2-135M-Instruct")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "180"))


@dataclass
class Chunk:
    text: str
    source: str
    title: str


def clean_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_markdown(path: Path, text: str, max_chars: int = 1800, overlap: int = 250) -> list[Chunk]:
    rel = path.relative_to(DOCS_DIR).as_posix()
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.M)
    title = title_match.group(1).strip() if title_match else path.stem

    sections = re.split(r"(?=^#{1,3}\s+)", text, flags=re.M)
    chunks: list[Chunk] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        section_title_match = re.search(r"^#{1,3}\s+(.+)$", section, flags=re.M)
        section_title = section_title_match.group(1).strip() if section_title_match else title
        if any(
            skip in section_title
            for skip in (
                "문서 개요",
                "핵심 요약",
                "상세 내용",
                "작업 절차",
                "주의사항",
                "오류 및 대응 방법",
                "원본 보존 내용",
                "기존 정리본 문서",
                "공통 작업 가능 여부",
            )
        ):
            continue

        start = 0
        while start < len(section):
            end = min(start + max_chars, len(section))
            part = section[start:end].strip()
            if len(part) >= 80:
                chunks.append(Chunk(text=part, source=rel, title=section_title))
            if end == len(section):
                break
            start = max(0, end - overlap)
    return chunks


def load_chunks() -> list[Chunk]:
    if not DOCS_DIR.exists():
        return []

    chunks: list[Chunk] = []
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel_parts = path.relative_to(DOCS_DIR).parts
        if rel_parts and rel_parts[0] == "HK_유지보수팀":
            continue
        if path.name in {"SIMPLIFY_CHANGELOG.md"}:
            continue
        text = clean_text(path.read_text(encoding="utf-8", errors="replace"))
        if text:
            chunks.extend(split_markdown(path, text))
    return chunks


class Retriever:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.vectors = [self._vector(f"{c.title}\n{c.source}\n{c.text}") for c in chunks]
        self.norms = [self._norm(v) for v in self.vectors]

    @staticmethod
    def _ngrams(text: str) -> list[str]:
        compact = re.sub(r"\s+", " ", text.lower())
        grams: list[str] = []
        for n in (2, 3, 4):
            grams.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
        tokens = re.findall(r"[가-힣A-Za-z0-9_./:@!+-]{2,}", text.lower())
        grams.extend(tokens)
        return grams

    @classmethod
    def _vector(cls, text: str) -> Counter[str]:
        return Counter(cls._ngrams(text))

    @staticmethod
    def _norm(vector: Counter[str]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))

    @staticmethod
    def _cosine(left: Counter[str], left_norm: float, right: Counter[str], right_norm: float) -> float:
        if not left_norm or not right_norm:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        dot = sum(value * right.get(key, 0) for key, value in left.items())
        return dot / (left_norm * right_norm)

    def search(self, query: str, top_k: int = 5) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        qv = self._vector(query)
        qn = self._norm(qv)
        query_terms = set(re.findall(r"[가-힣A-Za-z0-9_]{2,}", query.lower()))
        scored = []
        for idx, (vector, norm) in enumerate(zip(self.vectors, self.norms)):
            score = self._cosine(qv, qn, vector, norm)
            chunk = self.chunks[idx]
            source_title = f"{chunk.source} {chunk.title}".lower()
            folder = chunk.source.split("/", 1)[0].lower()
            folder_boost = 0.45 if folder and folder in query.lower() else 0.0
            exact_boost = sum(0.04 for term in query_terms if term in source_title)
            exact_boost += folder_boost
            scored.append((idx, score + exact_boost))
        scored.sort(key=lambda item: item[1], reverse=True)
        return [(self.chunks[idx], score) for idx, score in scored[:top_k] if score > 0]


class LocalLLM:
    def __init__(self):
        self.enabled = False
        self.error = ""
        self.tokenizer = None
        self.model = None
        if not USE_LLM:
            self.error = "USE_LLM=0"
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            self.model = AutoModelForCausalLM.from_pretrained(
                MODEL_NAME,
                torch_dtype=torch.float32,
                device_map="cpu",
                low_cpu_mem_usage=True,
            )
            self.model.eval()
            self.enabled = True
        except Exception as exc:
            self.error = str(exc)

    def generate(self, prompt: str) -> str:
        if not self.enabled or self.model is None or self.tokenizer is None:
            return ""

        import torch

        messages = [
            {
                "role": "system",
                "content": (
                    "너는 홈페이지코리아 유지보수 문서 RAG 챗봇이다. "
                    "반드시 제공된 근거 안에서만 답하고, 모르면 확인 필요라고 말한다. "
                    "계정, 경로, 서버, 주의사항은 임의로 바꾸지 않는다."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        if hasattr(self.tokenizer, "apply_chat_template"):
            text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        else:
            text = f"System: {messages[0]['content']}\nUser: {prompt}\nAssistant:"

        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=4096)
        with torch.no_grad():
            output = self.model.generate(
                **inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                temperature=None,
                top_p=None,
                repetition_penalty=1.08,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        return self.tokenizer.decode(generated, skip_special_tokens=True).strip()


llm_instance: LocalLLM | None = None


def get_llm() -> LocalLLM:
    global llm_instance
    if llm_instance is None:
        llm_instance = LocalLLM()
    return llm_instance


def build_context(results: list[tuple[Chunk, float]], max_chars: int = 5200) -> str:
    parts: list[str] = []
    used = 0
    for idx, (chunk, score) in enumerate(results, 1):
        item = (
            f"[근거 {idx}] score={score:.3f}\n"
            f"파일: {chunk.source}\n"
            f"섹션: {chunk.title}\n"
            f"{chunk.text}\n"
        )
        if used + len(item) > max_chars:
            break
        parts.append(item)
        used += len(item)
    return "\n---\n".join(parts)


def source_based_answer(query: str, results: list[tuple[Chunk, float]]) -> str:
    if not results:
        return "관련 문서를 찾지 못했습니다. 고객사명이나 기능명을 더 구체적으로 입력해 주세요."

    best_source = results[0][0].source
    primary = []
    seen_chunk_text: set[str] = set()
    seen_titles: set[str] = set()
    for chunk, score in results:
        if chunk.source != best_source:
            continue
        if chunk.title in seen_titles:
            continue
        seen_titles.add(chunk.title)
        key = re.sub(r"\s+", " ", chunk.text[:500])
        if key in seen_chunk_text:
            continue
        seen_chunk_text.add(key)
        primary.append((chunk, score))
    if not primary:
        primary = results[:2]

    lines = [
        "## 검색 기반 답변",
        "",
        f"질문과 가장 관련도가 높은 문서는 `{best_source}`입니다.",
        "",
        "### 핵심 근거",
    ]
    for idx, (chunk, score) in enumerate(primary[:3], 1):
        lines.append(f"{idx}. `{chunk.title}`")
        bullets = extract_readable_bullets(chunk.text)
        for bullet in bullets[:10]:
            lines.append(f"   - {bullet}")

    lines.extend(["", "### 참고 문서"])
    seen: set[str] = set()
    for chunk, score in results:
        key = f"{chunk.source}|{chunk.title}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}")
    return "\n".join(lines)


def extract_readable_bullets(text: str) -> list[str]:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = text.replace("아래 내용은 원본 md 문서의 본문 전체입니다.", "")
    text = text.replace("내용 누락 방지를 위해 원문 표현, 계정 정보, 경로, URL, 메모를 삭제하지 않고 보존했습니다.", "")

    candidates: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        if line.startswith("|") and line.endswith("|"):
            continue
        if line in {"```", "````markdown", "````"}:
            continue
        if len(line) > 220:
            parts = re.split(
                r"\s{2,}|(?<=\))\s+|(?<=!)\s+|(?=https?://)|(?=\b[a-zA-Z0-9_.-]{3,}\s+[A-Za-z0-9!@#$%^&*()_+=~.-]{4,})",
                line,
            )
            candidates.extend(part.strip() for part in parts if part.strip())
        else:
            candidates.append(line)

    important: list[str] = []
    keywords = [
        "http", "https", "id", "pw", "비밀번호", "계정", "인증", "접속", "경로",
        "서버", "관리자", "주의", "적용", "메인", "이미지", "inc", "ftp", "vpn",
    ]
    for line in candidates:
        lower = line.lower()
        if any(keyword in lower for keyword in keywords) or re.search(r"[/\\][\w가-힣./\\_-]+", line):
            important.append(line)
    for line in candidates:
        if line not in important:
            important.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for line in important:
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


chunks = load_chunks()
retriever = Retriever(chunks)


def retrieve(query: str, top_k: int) -> tuple[list[tuple[Chunk, float]], str]:
    query = query.strip()
    if not query:
        return [], ""

    results = retriever.search(query, top_k=top_k)
    context = build_context(results)
    return results, context


def immediate_answer(query: str, top_k: int) -> str:
    query = query.strip()
    if not query:
        return "질문을 입력해 주세요."

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    return source_based_answer(query, results)


def llm_answer(query: str, top_k: int) -> str:
    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 근거에 있는 내용만 사용
- 고객사별 작업 절차, 계정, 서버, 경로, 주의사항은 원문 그대로 유지
- 불확실하면 "확인 필요"라고 표시
- 마지막에 참고한 파일명을 bullet로 표시
"""
    llm = get_llm()
    generated = llm.generate(prompt)
    if not generated:
        generated = source_based_answer(query, results)

    sources = "\n".join(
        f"- `{chunk.source}` / {chunk.title} / score={score:.3f}"
        for chunk, score in results
    )
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def answer(query: str, top_k: int, history: list[dict] | None = None) -> str:
    if USE_LLM:
        return llm_answer(query, top_k)
    return immediate_answer(query, top_k)


def build_demo():
    import gradio as gr

    with gr.Blocks(title="HK Maintenance RAG Chatbot") as demo:
        gr.Markdown(
            f"""
# HK Maintenance RAG Chatbot

- 문서 경로: `{DOCS_DIR}`
- 문서 청크: `{len(chunks)}`
- LLM: `{MODEL_NAME if USE_LLM else "비활성"}`
"""
        )
        if USE_LLM:
            gr.Markdown("검색 결과를 먼저 표시한 뒤, LLM 답변이 준비되면 같은 답변 영역을 업데이트합니다.")
        try:
            chatbot = gr.Chatbot(type="messages", height=520)
        except TypeError:
            chatbot = gr.Chatbot(height=520)
        data_model_name = getattr(getattr(chatbot, "data_model", None), "__name__", "")
        chat_format = "messages" if "Messages" in data_model_name else "tuples"
        query = gr.Textbox(label="질문", placeholder="예: 대한항공 VPN 접속 방법 알려줘")
        top_k = gr.Slider(label="검색 근거 수", minimum=2, maximum=8, value=5, step=1)
        gr.ClearButton([query, chatbot])

        def normalize_history(chat_history: list | None) -> list:
            chat_history = chat_history or []
            normalized: list = []
            if chat_format == "messages":
                for item in chat_history:
                    if isinstance(item, dict) and "role" in item and "content" in item:
                        normalized.append(item)
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        user_msg, assistant_msg = item
                        normalized.append({"role": "user", "content": str(user_msg)})
                        normalized.append({"role": "assistant", "content": str(assistant_msg)})
                return normalized

            for item in chat_history:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    normalized.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict) and item.get("role") == "user":
                    normalized.append((str(item.get("content", "")), ""))
                elif isinstance(item, dict) and item.get("role") == "assistant":
                    if normalized and normalized[-1][1] == "":
                        normalized[-1] = (normalized[-1][0], str(item.get("content", "")))
                    else:
                        normalized.append(("", str(item.get("content", ""))))
            return normalized

        def respond(message: str, chat_history: list, k: int):
            chat_history = normalize_history(chat_history)
            bot_message = immediate_answer(message, int(k))
            if chat_format == "messages":
                chat_history = chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": bot_message},
                ]
            else:
                chat_history = chat_history + [(message, bot_message)]
            yield "", chat_history

            if not USE_LLM:
                return

            llm_message = llm_answer(message, int(k))
            combined = (
                f"{bot_message}\n\n"
                "---\n"
                "<details><summary>LLM 답변 보기</summary>\n\n"
                f"{llm_message}"
                "\n\n</details>"
            )
            if chat_format == "messages":
                chat_history[-1] = {"role": "assistant", "content": combined}
            else:
                chat_history[-1] = (message, combined)
            yield "", chat_history

        query.submit(respond, [query, chatbot, top_k], [query, chatbot])
    return demo


try:
    demo = build_demo()
except ModuleNotFoundError as exc:
    if exc.name != "gradio":
        raise
    demo = None


if __name__ == "__main__":
    if demo is None:
        raise SystemExit("gradio가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 실행하세요.")
    demo.launch(ssr_mode=False)
