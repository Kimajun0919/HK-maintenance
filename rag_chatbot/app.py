from __future__ import annotations

import os
import re
import math
import json
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DOCS_DIR = APP_DIR / "organized_maintenance_docs_simple"
if not DEFAULT_DOCS_DIR.exists():
    DEFAULT_DOCS_DIR = APP_DIR.parent / "organized_maintenance_docs_simple"
DOCS_DIR = Path(os.getenv("DOCS_DIR", DEFAULT_DOCS_DIR)).resolve()
MODEL_NAME = os.getenv("LOCAL_LLM_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")
USE_LLM = os.getenv("USE_LLM", "1") != "0"
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "512"))
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5")
ANTHROPIC_API_URL = os.getenv("ANTHROPIC_API_URL", "https://api.anthropic.com/v1/messages")


QUERY_ALIASES = {
    "시도지사": "시도지사협의회 대한시도지사협회",
    "대한시도지사": "시도지사협의회 대한시도지사협회",
    "차세대": "KIAPS_차세대 KIAPS",
    "대한항공": "대한항공씨앤디서비스 KCND",
    "안과": "안과의사회 대한안과의사회 KIOS",
    "고혈압": "고혈압학회 대한고혈압학회",
    "순환자원": "한국순환자원 한국순환자원유통지원센터 KORA",
    "성의교정": "성의교정_공동연구지원센터 성의교정_카톨릭대학교",
}

INTENT_EXPANSIONS = {
    "접속정보": "접속 정보 계정 로그인 관리자 URL VPN FTP 서버 클라우드 id pw password host 경로",
    "접속 정보": "접속 정보 계정 로그인 관리자 URL VPN FTP 서버 클라우드 id pw password host 경로",
    "계정": "계정 로그인 id pw password 관리자",
    "서버": "서버 host 경로 FTP VPN",
    "경로": "경로 디렉토리 폴더 서버 파일",
    "보고서": "보고서 월간 내역서 점검대장 발송",
}


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
                "확인 필요 사항",
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

    @staticmethod
    def _expand_query(query: str) -> str:
        expanded = [query]
        compact_query = query.replace(" ", "")
        for key, value in QUERY_ALIASES.items():
            if key.replace(" ", "") in compact_query:
                expanded.append(value)
        for key, value in INTENT_EXPANSIONS.items():
            if key.replace(" ", "") in compact_query:
                expanded.append(value)
        return " ".join(expanded)

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
        expanded_query = self._expand_query(query)
        qv = self._vector(expanded_query)
        qn = self._norm(qv)
        query_terms = set(re.findall(r"[가-힣A-Za-z0-9_]{2,}", expanded_query.lower()))
        compact_query = expanded_query.lower().replace(" ", "")
        wants_report = any(term in compact_query for term in ("보고서", "월간", "내역서", "점검대장"))
        wants_access = any(term in compact_query for term in ("접속정보", "접속", "계정", "로그인", "서버", "경로"))
        scored = []
        for idx, (vector, norm) in enumerate(zip(self.vectors, self.norms)):
            score = self._cosine(qv, qn, vector, norm)
            chunk = self.chunks[idx]
            source_title = f"{chunk.source} {chunk.title}".lower()
            folder = chunk.source.split("/", 1)[0].lower()
            folder_boost = 0.55 if folder and folder in compact_query else 0.0
            exact_boost = sum(0.04 for term in query_terms if term in source_title)
            exact_boost += folder_boost
            if folder == "공통자료" and not wants_report:
                exact_boost -= 0.35
            if wants_access:
                access_text = f"{chunk.title}\n{chunk.text}".lower()
                access_hits = sum(
                    1
                    for term in ("접속", "계정", "로그인", "관리자", "vpn", "ftp", "id", "pw", "password", "host", "클라우드", "경로")
                    if term in access_text
                )
                exact_boost += min(access_hits * 0.035, 0.28)
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
        if is_noise_title_for_answer(query, chunk.title):
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
        primary = [(chunk, score) for chunk, score in results[:2] if not is_noise_title_for_answer(query, chunk.title)]
    if not primary:
        primary = results[:1]

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
        if is_noise_title_for_answer(query, chunk.title):
            continue
        key = f"{chunk.source}|{chunk.title}"
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}")
    return "\n".join(lines)


def is_noise_title_for_answer(query: str, title: str) -> bool:
    compact_query = query.replace(" ", "")
    title_compact = title.replace(" ", "")
    noise_titles = (
        "문서개요",
        "핵심요약",
        "상세내용",
        "작업절차",
        "주의사항",
        "오류및대응방법",
        "관련이미지",
        "원본보존내용",
        "확인필요사항",
        "기존정리본문서",
        "HK매뉴얼에서확인된고객사별정보",
    )
    if any(noise in title_compact for noise in noise_titles):
        return True
    if "보고서" in title_compact and not any(term in compact_query for term in ("보고서", "월간", "내역", "점검")):
        return True
    return False


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


def claude_answer(query: str, top_k: int, api_key: str, model: str) -> str:
    api_key = api_key.strip()
    model = (model or DEFAULT_CLAUDE_MODEL).strip()
    if not api_key:
        return "Claude API 키를 입력해야 합니다."

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 작업명, 서버/계정/경로 같은 단어를 포함해 다시 질문해 주세요."

    sources = "\n".join(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}" for chunk, score in results)
    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 반드시 위 문서 근거 안의 내용만 사용하세요.
- 계정, 경로, 서버, 작업 절차, 주의사항은 원문 값을 임의로 바꾸지 마세요.
- 근거에 없으면 "확인 필요"라고 답하세요.
- 답변 마지막에 참고 문서 파일명을 bullet로 정리하세요.
"""
    payload = {
        "model": model,
        "max_tokens": MAX_NEW_TOKENS,
        "system": "당신은 HK 유지보수 문서 RAG 도우미입니다. 제공된 문서 근거만 바탕으로 한국어로 간결하고 정확하게 답변합니다.",
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"Claude API 오류({exc.code}): {body[:700]}"
    except Exception as exc:
        return f"Claude API 호출 실패: {exc}"

    parts = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")).strip())
    generated = "\n\n".join(part for part in parts if part)
    if not generated:
        generated = source_based_answer(query, results)
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


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
        generate_llm = gr.Checkbox(
            label="LLM 답변도 생성",
            value=False,
            interactive=USE_LLM,
            info="무료 CPU에서는 느리고 품질이 낮을 수 있습니다. 기본 답변은 검색 근거 기반입니다.",
        )
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

        def respond(message: str, chat_history: list, k: int, use_llm_for_question: bool):
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

            if not USE_LLM or not use_llm_for_question:
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

        query.submit(respond, [query, chatbot, top_k, generate_llm], [query, chatbot])
    return demo


try:
    demo = build_demo()
except ModuleNotFoundError as exc:
    if exc.name != "gradio":
        raise
    demo = None

WEB_DIR = APP_DIR / "web"


def _json_response(data, status_code: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(data, status_code=status_code)


def _safe_doc_path(source: str) -> Path | None:
    try:
        path = (DOCS_DIR / source).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if not path.exists() or path.suffix.lower() != ".md":
        return None
    return path


def _safe_asset_path(source: str, asset_path: str) -> Path | None:
    doc_path = _safe_doc_path(source)
    if doc_path is None:
        return None
    decoded_path = urllib.parse.unquote(asset_path).replace("\\", "/")
    try:
        path = (doc_path.parent / decoded_path).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if path.exists() and path.is_file():
        return path

    images_dir = doc_path.parent / "images"
    if images_dir.exists():
        original_name = Path(decoded_path).name
        doc_key = re.sub(r"_\d{8}$", "", doc_path.stem)
        name_match = re.match(r"image(?:\s+(\d+))?\.[A-Za-z0-9]+$", original_name, flags=re.I)
        if name_match:
            number = name_match.group(1)
            patterns = (
                [f"{doc_key}_image_{number}_*.png", f"*image_{number}_*.png"]
                if number
                else [f"{doc_key}_image_*.png", f"{doc_key}_image.*", "*image_*.png"]
            )
            candidates = []
            for pattern in patterns:
                candidates = sorted(images_dir.glob(pattern))
                if candidates:
                    break
            if candidates:
                return candidates[0].resolve()
        direct_matches = sorted(images_dir.glob(f"*{Path(original_name).stem.replace(' ', '_')}*"))
        if direct_matches:
            return direct_matches[0].resolve()
    return None


def docs_index() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not DOCS_DIR.exists():
        return items
    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR).as_posix()
        if path.name in {"SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
            continue
        parts = path.relative_to(DOCS_DIR).parts
        items.append({"source": rel, "title": path.stem, "customer": parts[0] if parts else ""})
    return items


def create_api_app():
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

    api_app = FastAPI(title="HK Maintenance Portal")

    @api_app.get("/", response_class=HTMLResponse)
    def home():
        index = WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>HK Maintenance Portal</h1><p>web/index.html is missing.</p>")

    @api_app.get("/healthz")
    def healthz():
        return {"ok": True, "docs_dir": str(DOCS_DIR), "chunks": len(chunks), "llm": MODEL_NAME if USE_LLM else "disabled"}

    @api_app.get("/api/meta")
    def api_meta():
        return {
            "docsDir": str(DOCS_DIR),
            "chunkCount": len(chunks),
            "docCount": len(docs_index()),
            "llm": MODEL_NAME if USE_LLM else "disabled",
            "claudeDefaultModel": DEFAULT_CLAUDE_MODEL,
        }

    @api_app.get("/api/docs")
    def api_docs():
        return {"docs": docs_index()}

    @api_app.get("/api/doc")
    def api_doc(source: str = Query(...)):
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        return {"source": source, "title": path.stem, "content": path.read_text(encoding="utf-8", errors="replace")}

    @api_app.get("/api/asset")
    def api_asset(source: str = Query(...), path: str = Query(...)):
        asset = _safe_asset_path(source, path)
        if asset is None:
            return _json_response({"error": "asset not found"}, status_code=404)
        return FileResponse(asset)

    @api_app.get("/api/search")
    def api_search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=10)):
        results, _context = retrieve(q, top_k)
        return {
            "query": q,
            "answer": source_based_answer(q, results),
            "results": [
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "score": round(score, 4),
                    "snippet": re.sub(r"\s+", " ", chunk.text).strip()[:700],
                }
                for chunk, score in results
            ],
        }

    @api_app.post("/api/chat")
    async def api_chat(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        query = str(payload.get("query", "")).strip()
        top_k = max(1, min(int(payload.get("topK", 5)), 10))
        use_llm = bool(payload.get("useLlm", False))
        if not query:
            return _json_response({"error": "query is required"}, status_code=400)
        provider = str(payload.get("provider", "quick")).strip().lower()
        if provider == "claude":
            response = claude_answer(
                query,
                top_k,
                str(payload.get("apiKey", "")),
                str(payload.get("model", DEFAULT_CLAUDE_MODEL)),
            )
        else:
            response = llm_answer(query, top_k) if use_llm and USE_LLM else immediate_answer(query, top_k)
        return {"query": query, "answer": response}

    @api_app.get("/robots.txt")
    def robots_txt():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    # Existing Gradio chatbot is intentionally not mounted in the portal.
    # if demo is not None:
    #     api_app = gr.mount_gradio_app(api_app, demo, path="/chat")
    return api_app


app = create_api_app() if demo is not None else None


if __name__ == "__main__":
    if demo is None:
        raise SystemExit("gradio가 설치되어 있지 않습니다. `pip install -r requirements.txt`를 실행하세요.")
    if app is None:
        demo.launch(ssr_mode=False)
    else:
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", "7860")))
