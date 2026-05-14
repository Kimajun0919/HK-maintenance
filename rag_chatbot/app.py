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
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "320"))


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
        if any(skip in section_title for skip in ("문서 개요", "핵심 요약", "원본 보존 내용", "기존 정리본 문서", "공통 작업 가능 여부")):
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

    lines = [
        "LLM 생성 없이 검색 근거를 기준으로 답합니다.",
        "",
        "확인된 관련 근거:",
    ]
    for idx, (chunk, score) in enumerate(results, 1):
        preview = re.sub(r"\s+", " ", chunk.text)[:450]
        lines.append(f"{idx}. `{chunk.source}` / {chunk.title} / score={score:.3f}")
        lines.append(f"   {preview}")
    return "\n".join(lines)


chunks = load_chunks()
retriever = Retriever(chunks)
llm = LocalLLM()


def answer(query: str, top_k: int, history: list[dict] | None = None) -> str:
    query = query.strip()
    if not query:
        return "질문을 입력해 주세요."

    results = retriever.search(query, top_k=top_k)
    context = build_context(results)
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
    generated = llm.generate(prompt)
    if not generated:
        generated = source_based_answer(query, results)

    sources = "\n".join(
        f"- `{chunk.source}` / {chunk.title} / score={score:.3f}"
        for chunk, score in results
    )
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def build_demo():
    import gradio as gr

    with gr.Blocks(title="HK Maintenance RAG Chatbot") as demo:
        gr.Markdown(
            f"""
# HK Maintenance RAG Chatbot

- 문서 경로: `{DOCS_DIR}`
- 문서 청크: `{len(chunks)}`
- LLM: `{MODEL_NAME if llm.enabled else "비활성 또는 로딩 실패"}`
"""
        )
        if llm.error:
            gr.Markdown(f"LLM 상태: `{llm.error[:500]}`")
        chatbot = gr.Chatbot(height=520)
        query = gr.Textbox(label="질문", placeholder="예: 대한항공 VPN 접속 방법 알려줘")
        top_k = gr.Slider(label="검색 근거 수", minimum=2, maximum=8, value=5, step=1)
        gr.ClearButton([query, chatbot])

        def respond(message: str, chat_history: list[tuple[str, str]], k: int):
            bot_message = answer(message, int(k), chat_history)
            chat_history = chat_history + [(message, bot_message)]
            return "", chat_history

        query.submit(respond, [query, chatbot, top_k], [query, chatbot])
    return demo


if __name__ == "__main__":
    build_demo().launch()
