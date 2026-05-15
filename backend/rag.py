from __future__ import annotations

import copy
import json as _json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

from config import DOCS_DIR, MAX_NEW_TOKENS, MODEL_NAME, USE_LLM
from models import Chunk
from storage import _doc_records, _init_supabase_storage

# ──────────────────────────────────────────────
# Query expansion tables (unchanged)
# ──────────────────────────────────────────────

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

# ──────────────────────────────────────────────
# Intent → retrieval / context budgets
# ──────────────────────────────────────────────
# Ordered from most-specific to most-general so detect_intent() returns
# the tightest match first.

INTENT_CONFIG: dict[str, dict] = {
    "access_info": {
        "keywords": ("접속", "로그인", "vpn", "ftp", "host", "경로", "url", "서버"),
        "top_k": 3,
        "candidate_k": 25,
        "max_context_chars": 1100,
        "snippets_per_chunk": 2,
    },
    "account_info": {
        "keywords": ("계정", "비밀번호", "아이디", "id", "pw", "password", "관리자", "권한"),
        "top_k": 3,
        "candidate_k": 25,
        "max_context_chars": 1200,
        "snippets_per_chunk": 2,
    },
    "report": {
        "keywords": ("보고서", "월간", "내역서", "점검대장", "발송"),
        "top_k": 4,
        "candidate_k": 30,
        "max_context_chars": 2000,
        "snippets_per_chunk": 3,
    },
    "troubleshooting": {
        "keywords": ("오류", "에러", "error", "문제", "장애", "복구", "점검", "유지보수"),
        "top_k": 5,
        "candidate_k": 35,
        "max_context_chars": 2800,
        "snippets_per_chunk": 3,
    },
    "feature_explanation": {
        "keywords": ("기능", "팝업", "ai", "인공지능", "요약", "프롬프트", "설정", "관리"),
        "top_k": 5,
        "candidate_k": 35,
        "max_context_chars": 2500,
        "snippets_per_chunk": 3,
    },
    "summary": {
        "keywords": ("요약", "정리", "전체", "개요", "비교", "차이"),
        "top_k": 8,
        "candidate_k": 40,
        "max_context_chars": 4000,
        "snippets_per_chunk": 2,
    },
    "general_search": {
        "keywords": (),
        "top_k": 5,
        "candidate_k": 40,
        "max_context_chars": 2200,
        "snippets_per_chunk": 2,
    },
}

# Set RAG_DEBUG=1 to print scoring details to stdout (server logs only)
_RAG_DEBUG = os.getenv("RAG_DEBUG", "0") != "0"

# ──────────────────────────────────────────────
# Text cleaning
# ──────────────────────────────────────────────


def clean_text(text: str) -> str:
    text = text.replace("﻿", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ──────────────────────────────────────────────
# Tokenization
# ──────────────────────────────────────────────

_kiwi_instance = None
_kiwi_available: bool | None = None  # None = not yet probed


def _try_kiwi_tokenize(text: str) -> list[str] | None:
    """Return morpheme tokens from kiwipiepy if installed, else None."""
    global _kiwi_instance, _kiwi_available
    if _kiwi_available is False:
        return None
    try:
        if _kiwi_instance is None:
            from kiwipiepy import Kiwi  # type: ignore
            _kiwi_instance = Kiwi()
        _kiwi_available = True
        return [t.form for t in _kiwi_instance.tokenize(text) if len(t.form) >= 2]
    except Exception:
        _kiwi_available = False
        return None


def tokenize(text: str) -> list[str]:
    """
    Unified tokenizer for BM25 corpus and query.
    Combines word tokens, Korean char n-grams, and optional kiwipiepy morphemes.
    Returns a list (with repetitions) so BM25 term-frequency counts work correctly.
    """
    normalized = re.sub(r"\s+", " ", text.lower()).strip()

    tokens: list[str] = []

    # Word-level tokens: Korean, English, numbers, and key symbols
    tokens.extend(re.findall(r"[가-힣A-Za-z0-9_./:@!+-]{2,}", normalized))

    # Korean character n-grams (2 and 3-gram) for spacing-variation tolerance
    korean_only = re.sub(r"[^가-힣]", "", normalized)
    for n in (2, 3):
        tokens.extend(korean_only[i : i + n] for i in range(max(0, len(korean_only) - n + 1)))

    # Optional morpheme tokens from kiwipiepy
    kiwi_tokens = _try_kiwi_tokenize(text)
    if kiwi_tokens:
        tokens.extend(kiwi_tokens)

    return tokens


def tokenize_for_field(text: str) -> list[str]:
    """Lighter tokenizer for field matching (title / source / folder) — word tokens only."""
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    return re.findall(r"[가-힣A-Za-z0-9_./:@!+-]{2,}", normalized)


# ──────────────────────────────────────────────
# BM25 Okapi (pure-Python, no extra dependency)
# ──────────────────────────────────────────────


class BM25Okapi:
    """
    Okapi BM25 over a pre-tokenized corpus.
    k1 and b follow the widely-used defaults (1.5 / 0.75).
    """

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.avgdl = sum(len(doc) for doc in corpus) / max(1, len(corpus))
        self.doc_freqs: list[Counter[str]] = [Counter(doc) for doc in corpus]

        # Document frequency per term
        df: Counter[str] = Counter()
        for tf in self.doc_freqs:
            for term in tf:
                df[term] += 1

        # IDF with Robertson-Spärck Jones smoothing (+1 to avoid log(0))
        self.idf: dict[str, float] = {
            term: math.log((self.corpus_size - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

    def score(self, query_tokens: list[str], doc_idx: int) -> float:
        tf = self.doc_freqs[doc_idx]
        dl = sum(tf.values())
        result = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            idf = self.idf.get(term, 0.0)
            freq = tf[term]
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            result += idf * numerator / denominator
        return result

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        return [self.score(query_tokens, i) for i in range(self.corpus_size)]


# ──────────────────────────────────────────────
# Markdown splitting (unchanged)
# ──────────────────────────────────────────────


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
    chunks: list[Chunk] = []
    for record in _doc_records():
        path = DOCS_DIR / record.source
        text = clean_text(record.content)
        if text:
            chunks.extend(split_markdown(path, text))
    return chunks


# ──────────────────────────────────────────────
# Intent detection
# ──────────────────────────────────────────────


def detect_intent(query: str) -> str:
    """Return the most specific intent category matching the query."""
    compact = query.lower().replace(" ", "")
    for intent, cfg in INTENT_CONFIG.items():
        if intent == "general_search":
            continue
        if any(kw in compact for kw in cfg["keywords"]):
            return intent
    return "general_search"


# ──────────────────────────────────────────────
# Retriever — BM25 + field-aware two-stage search
# ──────────────────────────────────────────────


class Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

        # BM25 index over body text
        body_corpus = [tokenize(c.text) for c in chunks]
        self.bm25: BM25Okapi | None = BM25Okapi(body_corpus) if chunks else None

        # Pre-tokenized fields for field-aware boost computation
        self.title_tokens = [tokenize_for_field(c.title) for c in chunks]
        self.source_tokens = [tokenize_for_field(c.source) for c in chunks]

        # Legacy cosine index — kept for fallback if BM25 raises unexpectedly
        self.vectors = [self._legacy_vector(f"{c.title}\n{c.source}\n{c.text}") for c in chunks]
        self.norms = [self._legacy_norm(v) for v in self.vectors]

    # ── Legacy cosine helpers ──────────────────────────────────────────────

    @staticmethod
    def _legacy_ngrams(text: str) -> list[str]:
        compact = re.sub(r"\s+", " ", text.lower())
        grams: list[str] = []
        for n in (2, 3, 4):
            grams.extend(compact[i : i + n] for i in range(max(0, len(compact) - n + 1)))
        grams.extend(re.findall(r"[가-힣A-Za-z0-9_./:@!+-]{2,}", text.lower()))
        return grams

    @classmethod
    def _legacy_vector(cls, text: str) -> Counter[str]:
        return Counter(cls._legacy_ngrams(text))

    @staticmethod
    def _legacy_norm(vector: Counter[str]) -> float:
        return math.sqrt(sum(v * v for v in vector.values()))

    @staticmethod
    def _legacy_cosine(
        left: Counter[str], left_norm: float, right: Counter[str], right_norm: float
    ) -> float:
        if not left_norm or not right_norm:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        dot = sum(v * right.get(k, 0) for k, v in left.items())
        return dot / (left_norm * right_norm)

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

    def _cosine_fallback(self, query: str, top_k: int) -> list[tuple[Chunk, float]]:
        """Original cosine-based search, preserved as fallback."""
        expanded_query = self._expand_query(query)
        qv = self._legacy_vector(expanded_query)
        qn = self._legacy_norm(qv)
        query_terms = set(re.findall(r"[가-힣A-Za-z0-9_]{2,}", expanded_query.lower()))
        compact_query = expanded_query.lower().replace(" ", "")
        wants_report = any(t in compact_query for t in ("보고서", "월간", "내역서", "점검대장"))
        wants_access = any(t in compact_query for t in ("접속정보", "접속", "계정", "로그인", "서버", "경로"))
        scored: list[tuple[int, float]] = []
        for idx, (vector, norm) in enumerate(zip(self.vectors, self.norms)):
            score = self._legacy_cosine(qv, qn, vector, norm)
            chunk = self.chunks[idx]
            source_title = f"{chunk.source} {chunk.title}".lower()
            folder = chunk.source.split("/", 1)[0].lower()
            folder_boost = 0.55 if folder and folder in compact_query else 0.0
            exact_boost = sum(0.04 for term in query_terms if term in source_title) + folder_boost
            if folder == "공통자료" and not wants_report:
                exact_boost -= 0.35
            if wants_access:
                access_hits = sum(
                    1
                    for t in ("접속", "계정", "로그인", "관리자", "vpn", "ftp", "id", "pw", "password", "host", "클라우드", "경로")
                    if t in f"{chunk.title}\n{chunk.text}".lower()
                )
                exact_boost += min(access_hits * 0.035, 0.28)
            scored.append((idx, score + exact_boost))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(self.chunks[idx], score) for idx, score in scored[:top_k] if score > 0]

    # ── BM25 + field-aware two-stage search ───────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 40,
        debug: bool = False,
    ) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        if self.bm25 is None:
            return self._cosine_fallback(query, top_k)

        expanded_query = self._expand_query(query)
        query_tokens = tokenize(expanded_query)
        query_terms_set = set(tokenize_for_field(expanded_query))
        compact_query = expanded_query.lower().replace(" ", "")
        query_compact_nospace = re.sub(r"\s+", "", query.lower())

        wants_report = any(t in compact_query for t in ("보고서", "월간", "내역서", "점검대장"))
        wants_access = any(t in compact_query for t in ("접속정보", "접속", "계정", "로그인", "서버", "경로"))

        if debug:
            print(f"[RAG_DEBUG] query_tokens (first 20): {query_tokens[:20]}")
            print(f"[RAG_DEBUG] expanded_query: {expanded_query[:120]}")

        # ── Stage 1: BM25 over all chunks → top candidate_k ───────────────
        try:
            bm25_scores = self.bm25.get_scores(query_tokens)
        except Exception:
            return self._cosine_fallback(query, top_k)

        max_bm25 = max(bm25_scores) if bm25_scores else 1.0
        if max_bm25 == 0.0:
            max_bm25 = 1.0

        candidate_indices = sorted(
            range(len(self.chunks)),
            key=lambda i: bm25_scores[i],
            reverse=True,
        )[:candidate_k]

        if debug:
            top_bm25 = bm25_scores[candidate_indices[0]] if candidate_indices else 0
            print(f"[RAG_DEBUG] candidate_k={len(candidate_indices)}, max BM25={top_bm25:.4f}")

        # ── Stage 2: Field-aware reranking over candidates ─────────────────
        _boost = _SETTINGS.get("boost", _DEFAULT_SETTINGS["boost"])
        scored: list[tuple[int, float]] = []
        for idx in candidate_indices:
            chunk = self.chunks[idx]
            bm25_norm = bm25_scores[idx] / max_bm25  # normalised to [0,1]
            folder = chunk.source.split("/", 1)[0].lower()
            title_lower = chunk.title.lower()
            source_lower = chunk.source.lower()
            body_lower = chunk.text.lower()

            # Title and source field hits
            title_hits = sum(1 for t in query_terms_set if t in title_lower)
            source_hits = sum(1 for t in query_terms_set if t in source_lower)
            title_boost = min(title_hits * _boost.get("title_per_hit", 0.12), _boost.get("title_cap", 0.36))
            source_boost = min(source_hits * _boost.get("source_per_hit", 0.07), _boost.get("source_cap", 0.21))

            # Folder name appears in query
            folder_boost = _boost.get("folder", 0.50) if folder and folder in compact_query else 0.0

            # Exact (space-collapsed) query phrase in title or source
            exact_phrase_boost = 0.0
            if len(query_compact_nospace) >= 4:
                if query_compact_nospace in re.sub(r"\s+", "", title_lower):
                    exact_phrase_boost = _boost.get("exact_phrase_title", 0.25)
                elif query_compact_nospace in re.sub(r"\s+", "", source_lower):
                    exact_phrase_boost = _boost.get("exact_phrase_source", 0.15)

            # Access-intent boost (preserve existing behaviour)
            access_boost = 0.0
            if wants_access:
                access_hits_n = sum(
                    1
                    for t in ("접속", "계정", "로그인", "관리자", "vpn", "ftp", "id", "pw", "password", "host", "클라우드", "경로")
                    if t in f"{title_lower}\n{body_lower}"
                )
                access_boost = min(access_hits_n * _boost.get("access_per_hit", 0.035), _boost.get("access_cap", 0.28))

            # 공통자료 penalty (preserve existing behaviour)
            common_penalty = _boost.get("common_folder_penalty", 0.35) if folder == "공통자료" and not wants_report else 0.0

            final_score = (
                bm25_norm
                + title_boost
                + source_boost
                + folder_boost
                + exact_phrase_boost
                + access_boost
                - common_penalty
            )

            if debug:
                boosts = []
                if title_boost:         boosts.append(f"title+{title_boost:.2f}")
                if source_boost:        boosts.append(f"src+{source_boost:.2f}")
                if folder_boost:        boosts.append(f"folder+{folder_boost:.2f}")
                if exact_phrase_boost:  boosts.append(f"exact+{exact_phrase_boost:.2f}")
                if access_boost:        boosts.append(f"access+{access_boost:.2f}")
                if common_penalty:      boosts.append(f"common_pen-{common_penalty:.2f}")
                print(
                    f"[RAG_DEBUG]   idx={idx} bm25={bm25_norm:.3f} "
                    f"final={final_score:.3f} {boosts} "
                    f"| {chunk.source[:35]}/{chunk.title[:25]}"
                )

            scored.append((idx, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [(self.chunks[idx], score) for idx, score in scored[:top_k] if score > 0]

        if debug:
            print(f"[RAG_DEBUG] returned {len(results)} results")

        return results


# ──────────────────────────────────────────────
# Local LLM (unchanged except system prompt)
# ──────────────────────────────────────────────


class LocalLLM:
    def __init__(self) -> None:
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
                    "You answer only using the provided context. "
                    "If the context does not contain enough information, say that the provided documents "
                    "do not contain enough information. "
                    "Do not guess. Do not invent URLs, credentials, schedules, costs, names, or technical details. "
                    "Answer concisely. When useful, mention the source title or section."
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


# ──────────────────────────────────────────────
# Context builders
# ──────────────────────────────────────────────


def _split_sentences(text: str) -> list[str]:
    """Split chunk text into sentences / short paragraphs for snippet extraction."""
    # Split on blank lines or sentence-ending punctuation followed by a capital / Korean start
    parts = re.split(r"\n{2,}|(?<=[.!?])\s+(?=[가-힣A-Z])", text)
    sentences: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > 300:
            for line in part.splitlines():
                line = line.strip()
                if len(line) >= 15:
                    sentences.append(line)
        else:
            sentences.append(part)
    return sentences


def extract_relevant_snippets(
    query: str,
    chunks: list[tuple[Chunk, float]],
    max_chars: int = 2500,
    snippets_per_chunk: int = 2,
) -> list[dict]:
    """
    For each retrieved chunk, select the most query-relevant sentences.
    Returns a list of source-card dicts with keys: source, title, score, text.
    Reduces LLM context size while preserving answer-relevant content.
    """
    query_tokens = set(tokenize_for_field(query))
    # Keywords whose presence in a sentence signals high value
    important_keywords = (
        "id", "pw", "password", "vpn", "ftp", "host", "http", "https",
        "접속", "계정", "경로", "서버", "관리자", "주의",
    )
    seen_snippets: set[str] = set()
    cards: list[dict] = []
    total_chars = 0

    for chunk, score in chunks:
        sentences = _split_sentences(chunk.text)
        # Score each sentence
        sentence_scores: list[tuple[float, str]] = []
        for sent in sentences:
            sent_lower = sent.lower()
            overlap = sum(1 for t in query_tokens if t in sent_lower)
            keyword_bonus = sum(0.5 for kw in important_keywords if kw in sent_lower)
            sentence_scores.append((overlap + keyword_bonus, sent))
        sentence_scores.sort(key=lambda x: x[0], reverse=True)

        selected: list[str] = []
        for _, sent in sentence_scores[: snippets_per_chunk * 2]:
            norm = re.sub(r"\s+", " ", sent).strip()
            if not norm or norm in seen_snippets or len(norm) < 15:
                continue
            seen_snippets.add(norm)
            selected.append(sent)
            if len(selected) >= snippets_per_chunk:
                break

        # Fallback: first usable sentence
        if not selected:
            for sent in sentences:
                norm = re.sub(r"\s+", " ", sent).strip()
                if norm and len(norm) >= 15 and norm not in seen_snippets:
                    seen_snippets.add(norm)
                    selected.append(sent)
                    break

        if not selected:
            continue

        card_text = f"[{chunk.source} / {chunk.title}]\n" + "\n".join(selected)
        if total_chars + len(card_text) > max_chars:
            remaining = max_chars - total_chars
            if remaining < 80:
                break
            card_text = card_text[:remaining]
        cards.append({"source": chunk.source, "title": chunk.title, "score": score, "text": card_text})
        total_chars += len(card_text)

    return cards


def build_context(results: list[tuple[Chunk, float]], max_chars: int = 5200) -> str:
    """Full-chunk context builder (preserved for /api/search and source_based_answer)."""
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


def build_compact_context(
    query: str,
    results: list[tuple[Chunk, float]],
    max_chars: int,
    snippets_per_chunk: int = 2,
) -> str:
    """Snippet-based compact context for LLM consumption."""
    cards = extract_relevant_snippets(query, results, max_chars=max_chars, snippets_per_chunk=snippets_per_chunk)
    if not cards:
        # Fallback to full-chunk context if snippet extraction yields nothing
        return build_context(results, max_chars)
    return "\n\n---\n\n".join(card["text"] for card in cards)


# ──────────────────────────────────────────────
# Answer helpers (unchanged)
# ──────────────────────────────────────────────


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
        primary = [(c, s) for c, s in results[:2] if not is_noise_title_for_answer(query, c.title)]
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
        for bullet in extract_readable_bullets(chunk.text)[:10]:
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
    if "보고서" in title_compact and not any(t in compact_query for t in ("보고서", "월간", "내역", "점검")):
        return True
    return False


def extract_readable_bullets(text: str) -> list[str]:
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = text.replace("아래 내용은 원본 md 문서의 본문 전체입니다.", "")
    text = text.replace(
        "내용 누락 방지를 위해 원문 표현, 계정 정보, 경로, URL, 메모를 삭제하지 않고 보존했습니다.", ""
    )

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
            candidates.extend(p.strip() for p in parts if p.strip())
        else:
            candidates.append(line)

    keywords = [
        "http", "https", "id", "pw", "비밀번호", "계정", "인증", "접속", "경로",
        "서버", "관리자", "주의", "적용", "메인", "이미지", "inc", "ftp", "vpn",
    ]
    important: list[str] = []
    for line in candidates:
        lower = line.lower()
        if any(kw in lower for kw in keywords) or re.search(r"[/\\][\w가-힣./\\_-]+", line):
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


# ──────────────────────────────────────────────
# Global index
# ──────────────────────────────────────────────

_init_supabase_storage()
chunks = load_chunks()
retriever = Retriever(chunks)
load_settings()  # apply settings.json after retriever is ready


def refresh_index() -> None:
    global chunks, retriever
    chunks = load_chunks()
    retriever = Retriever(chunks)
    _apply_settings_to_runtime()  # re-apply BM25 params to the new retriever


# ──────────────────────────────────────────────
# Retrieval entry points
# ──────────────────────────────────────────────


def retrieve(query: str, top_k: int) -> tuple[list[tuple[Chunk, float]], str]:
    """
    Standard retrieval for /api/search and immediate answers.
    Respects the caller's top_k exactly; uses intent-based candidate_k for stage-1 recall.
    Returns full-chunk context (backward-compatible).
    """
    query = query.strip()
    if not query:
        return [], ""

    intent = detect_intent(query)
    candidate_k = INTENT_CONFIG[intent]["candidate_k"]

    if _RAG_DEBUG:
        print(f"[RAG_DEBUG] retrieve() intent={intent} top_k={top_k} candidate_k={candidate_k}")

    results = retriever.search(query, top_k=top_k, candidate_k=candidate_k, debug=_RAG_DEBUG)
    context = build_context(results)
    return results, context


def retrieve_for_llm(query: str, top_k: int) -> tuple[list[tuple[Chunk, float]], str]:
    """
    Retrieval with compact snippet context for LLM consumption.
    When top_k is the default (5), uses intent-based top_k for tighter focus.
    Returns a compact context string instead of full chunks.
    """
    query = query.strip()
    if not query:
        return [], ""

    intent = detect_intent(query)
    cfg = INTENT_CONFIG[intent]
    # Only override top_k when the caller passed the default; respect explicit values
    effective_top_k = cfg["top_k"] if top_k == 5 else top_k
    candidate_k = cfg["candidate_k"]
    max_chars = cfg["max_context_chars"]
    snippets_per_chunk = cfg["snippets_per_chunk"]

    if _RAG_DEBUG:
        print(
            f"[RAG_DEBUG] retrieve_for_llm() intent={intent} "
            f"top_k={effective_top_k} candidate_k={candidate_k} max_chars={max_chars}"
        )

    results = retriever.search(query, top_k=effective_top_k, candidate_k=candidate_k, debug=_RAG_DEBUG)
    context = build_compact_context(query, results, max_chars=max_chars, snippets_per_chunk=snippets_per_chunk)

    if _RAG_DEBUG:
        print(f"[RAG_DEBUG] compact context length={len(context)}")

    return results, context


# ──────────────────────────────────────────────
# LLM prompt constants
# ──────────────────────────────────────────────

# Stricter system instruction — used in LocalLLM.generate() and exported for app.py
SYSTEM_INSTRUCTION_KO = (
    "제공된 문서 근거만 사용하여 답변합니다. "
    "근거에 충분한 정보가 없으면 '제공된 문서에 해당 정보가 없습니다'라고 답합니다. "
    "추측하지 않습니다. URL, 계정, 일정, 비용, 이름, 기술 정보를 임의로 만들지 않습니다. "
    "간결하게 답변하며, 관련 섹션 또는 파일명을 언급하면 더 좋습니다."
)


def _build_llm_user_prompt(query: str, context: str) -> str:
    return f"질문:\n{query}\n\n문서 근거:\n{context}\n\n한국어로 답변하세요."


# ──────────────────────────────────────────────
# Runtime settings
# ──────────────────────────────────────────────

_SETTINGS_FILE = Path(__file__).parent / "settings.json"

_DEFAULT_SETTINGS: dict = {
    "bm25": {"k1": 1.5, "b": 0.75},
    "boost": {
        "title_per_hit": 0.12,
        "title_cap": 0.36,
        "source_per_hit": 0.07,
        "source_cap": 0.21,
        "folder": 0.50,
        "exact_phrase_title": 0.25,
        "exact_phrase_source": 0.15,
        "access_per_hit": 0.035,
        "access_cap": 0.28,
        "common_folder_penalty": 0.35,
    },
    "intent": {
        "access_info":        {"top_k": 3, "candidate_k": 25, "max_context_chars": 1100, "snippets_per_chunk": 2},
        "account_info":       {"top_k": 3, "candidate_k": 25, "max_context_chars": 1200, "snippets_per_chunk": 2},
        "report":             {"top_k": 4, "candidate_k": 30, "max_context_chars": 2000, "snippets_per_chunk": 3},
        "troubleshooting":    {"top_k": 5, "candidate_k": 35, "max_context_chars": 2800, "snippets_per_chunk": 3},
        "feature_explanation":{"top_k": 5, "candidate_k": 35, "max_context_chars": 2500, "snippets_per_chunk": 3},
        "summary":            {"top_k": 8, "candidate_k": 40, "max_context_chars": 4000, "snippets_per_chunk": 2},
        "general_search":     {"top_k": 5, "candidate_k": 40, "max_context_chars": 2200, "snippets_per_chunk": 2},
    },
    "prompt": {"system_instruction": SYSTEM_INSTRUCTION_KO},
    "general": {"max_new_tokens": 512},
}

_SETTINGS: dict = copy.deepcopy(_DEFAULT_SETTINGS)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _apply_settings_to_runtime() -> None:
    """Push _SETTINGS values into live runtime objects (called after load or save)."""
    global SYSTEM_INSTRUCTION_KO, INTENT_CONFIG
    SYSTEM_INSTRUCTION_KO = _SETTINGS.get("prompt", {}).get(
        "system_instruction", _DEFAULT_SETTINGS["prompt"]["system_instruction"]
    )
    intent_overrides = _SETTINGS.get("intent", {})
    for intent_name, values in intent_overrides.items():
        if intent_name in INTENT_CONFIG and isinstance(values, dict):
            INTENT_CONFIG[intent_name].update(values)
    # Update BM25 hyper-params on the live retriever without rebuilding the index
    if retriever is not None and retriever.bm25 is not None:
        bm25_cfg = _SETTINGS.get("bm25", {})
        retriever.bm25.k1 = float(bm25_cfg.get("k1", 1.5))
        retriever.bm25.b = float(bm25_cfg.get("b", 0.75))


def load_settings() -> dict:
    """Load settings.json if present and merge over defaults; apply to runtime."""
    global _SETTINGS
    _SETTINGS = copy.deepcopy(_DEFAULT_SETTINGS)
    if _SETTINGS_FILE.exists():
        try:
            with _SETTINGS_FILE.open(encoding="utf-8") as f:
                saved = _json.load(f)
            _SETTINGS = _deep_merge(_SETTINGS, saved)
        except Exception:
            pass
    _apply_settings_to_runtime()
    return _SETTINGS


def save_settings(patch: dict) -> dict:
    """Merge patch into _SETTINGS, persist to settings.json, apply to runtime."""
    global _SETTINGS
    _SETTINGS = _deep_merge(_SETTINGS, patch)
    try:
        with _SETTINGS_FILE.open("w", encoding="utf-8") as f:
            _json.dump(_SETTINGS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    _apply_settings_to_runtime()
    return _SETTINGS


def get_settings() -> dict:
    result = copy.deepcopy(_SETTINGS)
    result["_defaults"] = copy.deepcopy(_DEFAULT_SETTINGS)
    return result


def reset_settings() -> dict:
    """Overwrite settings.json with defaults and apply."""
    global _SETTINGS
    _SETTINGS = copy.deepcopy(_DEFAULT_SETTINGS)
    try:
        with _SETTINGS_FILE.open("w", encoding="utf-8") as f:
            _json.dump(_SETTINGS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    _apply_settings_to_runtime()
    return get_settings()


# ──────────────────────────────────────────────
# Answer functions
# ──────────────────────────────────────────────


def immediate_answer(query: str, top_k: int) -> str:
    query = query.strip()
    if not query:
        return "질문을 입력해 주세요."

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    return source_based_answer(query, results)


def llm_answer(query: str, top_k: int) -> str:
    results, context = retrieve_for_llm(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요."

    prompt = _build_llm_user_prompt(query, context)
    llm = get_llm()
    generated = llm.generate(prompt)
    if not generated:
        generated = source_based_answer(query, results)

    sources = "\n".join(
        f"- `{chunk.source}` / {chunk.title} / score={score:.3f}"
        for chunk, score in results
    )
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def answer(query: str, top_k: int, _history: list[dict] | None = None) -> str:
    if USE_LLM:
        return llm_answer(query, top_k)
    return immediate_answer(query, top_k)
