from __future__ import annotations

import copy
import hashlib
import json as _json
import math
import os
import re
import time
from collections import Counter
from pathlib import Path

from config import DOCS_DIR, EMBEDDING_DIM, EMBEDDING_MODEL_NAME, MAX_NEW_TOKENS, MODEL_NAME, SUPABASE_ENABLED, USE_LLM
from models import Chunk
from storage import (
    _db_delete_stale_chunks,
    _db_existing_chunk_hashes,
    _db_upsert_search_chunks,
    _db_vector_search_chunks,
    _doc_records,
    _init_supabase_storage,
)

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


def normalize_search_text(text: str) -> str:
    """Normalize text for search without changing the original document content."""
    text = (text or "").lower()
    text = re.sub(r"a\s*[/.\-]?\s*s|에이에스", "as", text, flags=re.I)
    text = re.sub(r"[^0-9a-z\uac00-\ud7a3\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_search_text(text: str) -> str:
    return re.sub(r"\s+", "", normalize_search_text(text))


def word_tokens(text: str) -> list[str]:
    return re.findall(r"[0-9a-z\uac00-\ud7a3]{1,}", normalize_search_text(text))


def bm25_tokens(text: str) -> list[str]:
    return [token for token in word_tokens(text) if len(token) >= 2 or token.isdigit()]


def char_ngram_tokens(text: str) -> set[str]:
    normalized = normalize_search_text(text)
    compact = compact_search_text(text)
    grams: set[str] = set(re.findall(r"[0-9a-z]+", normalized))
    korean = re.sub(r"[^\uac00-\ud7a3]", "", normalized)
    for value in (korean, compact):
        for n in (2, 3):
            grams.update(value[i : i + n] for i in range(max(0, len(value) - n + 1)))
    return {gram for gram in grams if len(gram) >= 2}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _stable_document_id(source: str) -> str:
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]


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


def split_markdown(path: Path, text: str, max_chars: int = 1800, overlap: int = 250, updated_at: str | None = None) -> list[Chunk]:
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
                chunk_no = len(chunks) + 1
                folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
                document_id = _stable_document_id(rel)
                chunks.append(
                    Chunk(
                        text=part,
                        source=rel,
                        title=title,
                        document_id=document_id,
                        chunk_id=f"{document_id}_chunk_{chunk_no:04d}",
                        heading=section_title,
                        filename=path.name,
                        folder=folder,
                        updated_at=updated_at,
                        normalized_body=normalize_search_text(part),
                        compact_body=compact_search_text(part),
                    )
                )
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
            chunks.extend(split_markdown(path, text, updated_at=record.updated_at))
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


def expand_query_terms(query: str) -> dict:
    cfg = _SETTINGS.get("synonyms", {}) if "_SETTINGS" in globals() else {}
    synonyms = cfg.get("synonyms", {}) if isinstance(cfg, dict) else {}
    normalized_query = normalize_search_text(query)
    terms = word_tokens(normalized_query)
    expanded: list[dict] = []
    seen: set[str] = set()
    if isinstance(synonyms, dict) and synonyms:
        for term in terms:
            for synonym in synonyms.get(term, []) or []:
                normalized_synonym = normalize_search_text(str(synonym))
                if normalized_synonym and normalized_synonym not in seen and normalized_synonym not in terms:
                    seen.add(normalized_synonym)
                    expanded.append({"term": normalized_synonym, "weight": 0.6, "source": term})
    return {
        "normalized_query": normalized_query,
        "terms": terms,
        "expanded_terms": expanded,
        "synonym_used": bool(expanded),
    }


def calculate_recency_boost(updated_at: str | None, max_boost: float = 0.05) -> float:
    if not updated_at or max_boost <= 0:
        return 0.0
    try:
        from datetime import datetime, timezone

        value = updated_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 86400)
        return max(0.0, max_boost * (1.0 - min(age_days, 365.0) / 365.0))
    except Exception:
        return 0.0


class EmbeddingStore:
    """
    Stores deterministic chunk embeddings keyed by chunk content hash.
    If a local embedding model is not configured, a hashed lexical embedding is used
    so reranking remains cached and dependency-free.
    """

    _model = None
    _model_failed = False

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim
        self.vectors: dict[str, list[float]] = {}
        self.hashes: dict[str, str] = {}
        self.cache_path = Path(__file__).parent / ".embedding_cache.json"
        self.dirty = False
        self._load()

    def _load(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            with self.cache_path.open(encoding="utf-8") as f:
                payload = _json.load(f)
            if int(payload.get("dim", self.dim)) != self.dim:
                return
            self.hashes = {str(k): str(v) for k, v in payload.get("hashes", {}).items()}
            self.vectors = {
                str(k): [float(x) for x in v]
                for k, v in payload.get("vectors", {}).items()
                if isinstance(v, list) and len(v) == self.dim
            }
        except Exception:
            self.hashes = {}
            self.vectors = {}

    def save(self) -> None:
        if not self.dirty:
            return
        try:
            with self.cache_path.open("w", encoding="utf-8") as f:
                _json.dump({"dim": self.dim, "hashes": self.hashes, "vectors": self.vectors}, f)
            self.dirty = False
        except Exception:
            pass

    def text_hash(self, text: str) -> str:
        backend = os.getenv("EMBEDDING_BACKEND", "sentence-transformers").lower()
        signature = f"{backend}:{EMBEDDING_MODEL_NAME}:{self.dim}"
        return hashlib.sha256(f"{signature}\n{normalize_search_text(text)}".encode("utf-8")).hexdigest()

    def embed_text(self, text: str) -> list[float]:
        if os.getenv("EMBEDDING_BACKEND", "sentence-transformers").lower() in {"hash", "fallback"}:
            return self._hash_embedding(text)
        model = self._load_model()
        if model is not None:
            try:
                vector = model.encode(
                    normalize_search_text(text),
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
                values = [float(value) for value in vector.tolist()]
                if len(values) == self.dim:
                    return values
                if len(values) > self.dim:
                    return values[: self.dim]
                return values + [0.0] * (self.dim - len(values))
            except Exception:
                type(self)._model_failed = True
                return []
        return []

    def _hash_embedding(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = bm25_tokens(text) + list(char_ngram_tokens(text))
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm:
            vector = [v / norm for v in vector]
        return vector

    @staticmethod
    def chunk_embedding_text(chunk: Chunk) -> str:
        fields = [
            ("문서 제목", chunk.title),
            ("폴더", chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else "")),
            ("파일명", chunk.filename or chunk.source.rsplit("/", 1)[-1]),
            ("소제목", chunk.heading or ""),
            ("내용", chunk.text),
        ]
        return "\n".join(f"{label}: {value}" for label, value in fields if str(value or "").strip())

    @classmethod
    def _load_model(cls):
        if os.getenv("EMBEDDING_BACKEND", "sentence-transformers").lower() in {"hash", "fallback", "none"}:
            return None
        if cls._model_failed:
            return None
        if cls._model is not None:
            return cls._model
        try:
            from sentence_transformers import SentenceTransformer

            cls._model = SentenceTransformer(EMBEDDING_MODEL_NAME)
            return cls._model
        except Exception:
            cls._model_failed = True
            return None

    def get_chunk_embedding(self, chunk: Chunk, force: bool = False) -> list[float]:
        chunk_id = chunk.chunk_id or f"{chunk.source}:{chunk.title}:{hashlib.sha1(chunk.text.encode('utf-8')).hexdigest()[:12]}"
        content = self.chunk_embedding_text(chunk)
        content_hash = self.text_hash(content)
        if force or self.hashes.get(chunk_id) != content_hash or chunk_id not in self.vectors:
            self.vectors[chunk_id] = self.embed_text(content)
            self.hashes[chunk_id] = content_hash
            self.dirty = True
        return self.vectors.get(chunk_id, [])


class Retriever:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks

        # BM25 index over normalized chunk body + important metadata fields.
        body_corpus = [bm25_tokens(self._searchable_text(c)) for c in chunks]
        self.bm25: BM25Okapi | None = BM25Okapi(body_corpus) if chunks else None

        self.normalized_fields = [self._normalized_fields(c) for c in chunks]
        self.ngram_sets = [char_ngram_tokens(self._searchable_text(c)) for c in chunks]
        self.embedding_store = EmbeddingStore()
        self.embeddings = [[] for _chunk in chunks]
        self.embedding_store.save()
        self.chunk_index_by_id = {chunk.chunk_id: idx for idx, chunk in enumerate(chunks) if chunk.chunk_id}
        self.last_score_details: dict[str, dict] = {}
        self.last_debug: dict = {}

        # Legacy cosine index — kept for fallback if BM25 raises unexpectedly
        self.vectors = [self._legacy_vector(f"{c.title}\n{c.source}\n{c.text}") for c in chunks]
        self.norms = [self._legacy_norm(v) for v in self.vectors]

    @staticmethod
    def _searchable_text(chunk: Chunk) -> str:
        return "\n".join(
            [
                chunk.title or "",
                chunk.heading or "",
                chunk.filename or "",
                chunk.folder or "",
                chunk.source or "",
                chunk.text or "",
            ]
        )

    @staticmethod
    def _normalized_fields(chunk: Chunk) -> dict[str, str]:
        folder = chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else "")
        filename = chunk.filename if chunk.filename is not None else chunk.source.rsplit("/", 1)[-1]
        return {
            "title": normalize_search_text(chunk.title),
            "filename": normalize_search_text(filename),
            "folder": normalize_search_text(folder),
            "heading": normalize_search_text(chunk.heading or chunk.title),
            "body": normalize_search_text(chunk.text),
            "compact_title": compact_search_text(chunk.title),
            "compact_filename": compact_search_text(filename),
            "compact_folder": compact_search_text(folder),
            "compact_heading": compact_search_text(chunk.heading or chunk.title),
            "compact_body": compact_search_text(chunk.text),
        }

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

    def _hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 40,
        debug: bool = False,
        mode: str = "hybrid",
    ) -> list[tuple[Chunk, float]]:
        mode = mode if mode in {"hybrid", "bm25_only", "ngram_only", "vector_only"} else "hybrid"
        search_cfg = _SETTINGS.get("search", _DEFAULT_SETTINGS["search"])
        weights = search_cfg.get("weights", _DEFAULT_SETTINGS["search"]["weights"])
        field_cfg = search_cfg.get("field_boosts", _DEFAULT_SETTINGS["search"]["field_boosts"])
        candidate_limits = search_cfg.get("candidate_limits", _DEFAULT_SETTINGS["search"].get("candidate_limits", {}))
        legacy_candidate_limit = int(search_cfg.get("candidate_limit", candidate_k) or candidate_k)
        bm25_limit = int(candidate_limits.get("bm25", legacy_candidate_limit) or legacy_candidate_limit)
        ngram_limit = int(candidate_limits.get("ngram", legacy_candidate_limit) or legacy_candidate_limit)
        vector_limit = int(candidate_limits.get("vector", legacy_candidate_limit) or legacy_candidate_limit)
        merged_max = int(candidate_limits.get("merged_max", max(candidate_k, legacy_candidate_limit)) or candidate_k)
        bm25_limit = max(1, min(bm25_limit, len(self.chunks)))
        ngram_limit = max(1, min(ngram_limit, len(self.chunks)))
        vector_limit = max(0, vector_limit)
        merged_max = max(1, min(merged_max, len(self.chunks)))

        query_info = expand_query_terms(query)
        query_text = " ".join([query_info["normalized_query"]] + [item["term"] for item in query_info["expanded_terms"]])
        query_tokens = bm25_tokens(query_text)
        original_terms = set(word_tokens(query))
        expanded_terms = {item["term"] for item in query_info["expanded_terms"]}
        query_ngrams = char_ngram_tokens(query_text)
        query_embedding = self.embedding_store.embed_text(query_text)
        embedding_available = bool(query_embedding)
        normalized_query = query_info["normalized_query"]
        compact_query = compact_search_text(query)

        try:
            bm25_scores = self.bm25.get_scores(query_tokens) if self.bm25 else []
        except Exception:
            return self._cosine_fallback(query, top_k)
        max_bm25 = max(bm25_scores) if bm25_scores else 1.0
        if max_bm25 <= 0:
            max_bm25 = 1.0
        ngram_scores = [jaccard_similarity(query_ngrams, grams) for grams in self.ngram_sets]
        bm25_indices = sorted(range(len(self.chunks)), key=lambda i: bm25_scores[i], reverse=True)[:bm25_limit]
        ngram_indices = sorted(range(len(self.chunks)), key=lambda i: ngram_scores[i], reverse=True)[:ngram_limit]

        vector_scores_by_id: dict[str, float] = {}
        vector_indices: list[int] = []
        vector_error: str | None = None
        if SUPABASE_ENABLED and embedding_available and vector_limit > 0:
            try:
                for row in _db_vector_search_chunks(query_embedding, vector_limit):
                    chunk_id = row.get("chunk_id")
                    if not chunk_id:
                        continue
                    vector_scores_by_id[chunk_id] = float(row.get("similarity", 0.0))
                    idx = self.chunk_index_by_id.get(chunk_id)
                    if idx is not None:
                        vector_indices.append(idx)
            except Exception as exc:
                vector_error = str(exc)

        sources_by_idx: dict[int, set[str]] = {}
        for source_name, indices in (("bm25", bm25_indices), ("ngram", ngram_indices), ("vector", vector_indices)):
            for idx in indices:
                sources_by_idx.setdefault(idx, set()).add(source_name)

        if mode == "bm25_only":
            candidate_indices = bm25_indices
        elif mode == "ngram_only":
            candidate_indices = ngram_indices
        elif mode == "vector_only":
            candidate_indices = vector_indices
        else:
            candidate_indices = sorted(
                sources_by_idx,
                key=lambda i: (
                    (bm25_scores[i] / max_bm25) * float(weights.get("bm25", 0.35))
                    + ngram_scores[i] * float(weights.get("ngram", 0.15))
                    + vector_scores_by_id.get(self.chunks[i].chunk_id or "", 0.0) * float(weights.get("embedding", 0.35))
                ),
                reverse=True,
            )[:merged_max]

        scored: list[tuple[int, float]] = []
        self.last_score_details = {}
        self.last_debug = {
            "original_query": query,
            "normalized_query": normalized_query,
            "mode": mode,
            "expanded_terms": [item["term"] for item in query_info["expanded_terms"]],
            "synonym_used": query_info["synonym_used"],
            "candidate_count": len(candidate_indices),
            "bm25_candidate_count": len(bm25_indices),
            "ngram_candidate_count": len(ngram_indices),
            "vector_candidate_count": len(vector_indices),
            "merged_candidate_count": len(candidate_indices),
            "vector_retrieval_enabled": SUPABASE_ENABLED,
            "vector_retrieval_error": vector_error,
            "embedding_available": embedding_available,
            "embedding_model": EMBEDDING_MODEL_NAME if embedding_available else None,
        }
        debug_candidates: dict[str, list[dict]] = {"bm25": [], "ngram": [], "vector": []} if debug else {}
        final_debug_results: list[dict] = [] if debug else []
        for idx in candidate_indices:
            chunk = self.chunks[idx]
            fields = self.normalized_fields[idx]
            bm25_norm = bm25_scores[idx] / max_bm25
            ngram_score = ngram_scores[idx]
            chunk_embedding = self.embeddings[idx] if idx < len(self.embeddings) else []
            vector_embedding_score = vector_scores_by_id.get(chunk.chunk_id or "")
            if vector_embedding_score is not None:
                embedding_score = vector_embedding_score
            elif embedding_available and chunk_embedding:
                embedding_score = max(0.0, min(1.0, cosine_similarity(query_embedding, chunk_embedding)))
            elif embedding_available:
                chunk_embedding = self.embedding_store.get_chunk_embedding(chunk)
                if idx < len(self.embeddings):
                    self.embeddings[idx] = chunk_embedding
                embedding_score = max(0.0, min(1.0, cosine_similarity(query_embedding, chunk_embedding))) if chunk_embedding else 0.0
            else:
                embedding_score = 0.0

            field_raw = 0.0
            for field_name, boost in field_cfg.items():
                field_text = fields.get(field_name, "")
                if any(term and term in field_text for term in original_terms):
                    field_raw += float(boost)
                elif any(term and term in field_text for term in expanded_terms):
                    field_raw += float(boost) * 0.6
            field_boost = min(field_raw, float(search_cfg.get("field_boost_cap", 0.35)))

            full_text = " ".join(fields.get(k, "") for k in ("title", "filename", "folder", "heading", "body"))
            full_compact = "".join(fields.get(k, "") for k in ("compact_title", "compact_filename", "compact_folder", "compact_heading", "compact_body"))
            exact_match_boost = 0.0
            if normalized_query and normalized_query in full_text:
                exact_match_boost += float(search_cfg.get("exact_phrase_boost", 0.05))
            if compact_query and len(compact_query) >= 2 and compact_query in full_compact:
                exact_match_boost += float(search_cfg.get("compact_exact_phrase_boost", 0.03))
            exact_match_boost = min(exact_match_boost, 0.08)

            recency_boost = calculate_recency_boost(chunk.updated_at, float(weights.get("recency_boost_max", 0.05)))
            final_score = (
                bm25_norm * float(weights.get("bm25", 0.35))
                + ngram_score * float(weights.get("ngram", 0.15))
                + embedding_score * float(weights.get("embedding", 0.35))
                + field_boost * float(weights.get("field_boost", 0.10))
                + exact_match_boost * float(weights.get("exact_match_boost", 0.05))
                + recency_boost
            )
            ranking_score = final_score
            if mode == "bm25_only":
                ranking_score = bm25_norm
            elif mode == "ngram_only":
                ranking_score = ngram_score
            elif mode == "vector_only":
                ranking_score = embedding_score
            detail = {
                "bm25": round(bm25_norm, 4),
                "ngram": round(ngram_score, 4),
                "embedding": round(embedding_score, 4),
                "field_boost": round(field_boost, 4),
                "exact_match_boost": round(exact_match_boost, 4),
                "recency_boost": round(recency_boost, 4),
                "sources": {
                    "bm25": "bm25" in sources_by_idx.get(idx, set()),
                    "ngram": "ngram" in sources_by_idx.get(idx, set()),
                    "vector": "vector" in sources_by_idx.get(idx, set()),
                },
                "synonym_used": query_info["synonym_used"],
                "expanded_terms": [item["term"] for item in query_info["expanded_terms"]],
            }
            self.last_score_details[chunk.chunk_id or str(idx)] = detail
            if debug and _RAG_DEBUG:
                print(f"[RAG_DEBUG] idx={idx} final={final_score:.3f} detail={detail}")
            scored.append((idx, ranking_score))

            if debug:
                debug_item = self._debug_candidate_item(chunk, detail, final_score)
                if idx in bm25_indices:
                    debug_candidates["bm25"].append(debug_item)
                if idx in ngram_indices:
                    debug_candidates["ngram"].append(debug_item)
                if idx in vector_indices:
                    debug_candidates["vector"].append(debug_item)
                final_debug_results.append(debug_item)

        scored.sort(key=lambda x: x[1], reverse=True)
        if debug:
            self.last_debug["candidates"] = {
                "bm25": sorted(debug_candidates["bm25"], key=lambda item: item["bm25_score"], reverse=True)[:10],
                "ngram": sorted(debug_candidates["ngram"], key=lambda item: item["ngram_score"], reverse=True)[:10],
                "vector": sorted(debug_candidates["vector"], key=lambda item: item["embedding_score"], reverse=True)[:10],
            }
            self.last_debug["final_results"] = sorted(final_debug_results, key=lambda item: item["final_score"], reverse=True)[:10]
        return [(self.chunks[idx], score) for idx, score in scored[:top_k] if score > 0]

    @staticmethod
    def _debug_candidate_item(chunk: Chunk, detail: dict, final_score: float) -> dict:
        return {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id or _stable_document_id(chunk.source),
            "title": chunk.title,
            "filename": chunk.filename or chunk.source.rsplit("/", 1)[-1],
            "folder": chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else ""),
            "heading": chunk.heading or chunk.title,
            "matched_text": re.sub(r"\s+", " ", chunk.text).strip()[:700],
            "sources": detail.get("sources", {}),
            "bm25_score": detail.get("bm25", 0.0),
            "ngram_score": detail.get("ngram", 0.0),
            "embedding_score": detail.get("embedding", 0.0),
            "field_boost": detail.get("field_boost", 0.0),
            "exact_match_boost": detail.get("exact_match_boost", 0.0),
            "final_score": round(final_score, 4),
        }

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 40,
        debug: bool = False,
        mode: str = "hybrid",
    ) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        if self.bm25 is None:
            return self._cosine_fallback(query, top_k)
        return self._hybrid_search(query, top_k=top_k, candidate_k=candidate_k, debug=debug, mode=mode)

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
        "문서정보",
        "핵심요약",
        "요약",
        "본문",
        "상세내용",
        "정리검증",
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


def is_low_value_context_title(title: str) -> bool:
    title_compact = title.replace(" ", "")
    low_value_titles = (
        "문서개요",
        "문서정보",
        "핵심요약",
        "요약",
        "본문",
        "정리검증",
        "상세내용",
        "원본보존내용",
        "확인필요사항",
        "기존정리본문서",
        "HK매뉴얼에서확인된고객사별정보",
    )
    return any(noise in title_compact for noise in low_value_titles)


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
    return (
        "질문:\n"
        f"{query}\n\n"
        "문서 근거:\n"
        f"{context}\n\n"
        "답변 지침:\n"
        "- 먼저 질문에 대한 결론을 자연스러운 한국어로 답하세요.\n"
        "- 단순히 참고 문서 목록을 나열하지 말고, 문서 내용을 업무자가 이해하기 쉽게 풀어 설명하세요.\n"
        "- 문서에 있는 사실만 사용하세요. 문서에 없는 일반 지식, 위치, 기능, 비용, 계정, URL은 만들지 마세요.\n"
        "- 문서에 정보가 부족하면 무엇이 부족한지 분명히 말하고, 확인된 정보만 정리하세요.\n"
        "- 필요하면 마지막에 근거 파일명이나 섹션명을 짧게 덧붙이세요.\n"
        "- 최종 답변만 작성하고 추론 과정은 출력하지 마세요."
    )


# ──────────────────────────────────────────────
# Runtime settings  (defined before global init so load_settings() is callable)
# ──────────────────────────────────────────────

_SETTINGS_FILE = Path(__file__).parent / "settings.json"

_DEFAULT_SETTINGS: dict = {
    "bm25": {"k1": 1.5, "b": 0.75},
    "synonyms": {"synonyms": {}},
    "search": {
        "weights": {
            "bm25": 0.35,
            "ngram": 0.15,
            "embedding": 0.35,
            "field_boost": 0.10,
            "exact_match_boost": 0.05,
            "recency_boost_max": 0.05,
        },
        "candidate_limit": 50,
        "candidate_limits": {
            "bm25": 50,
            "ngram": 50,
            "vector": 50,
            "merged_max": 100,
        },
        "field_boost_cap": 0.35,
        "exact_phrase_boost": 0.05,
        "compact_exact_phrase_boost": 0.03,
        "field_boosts": {
            "title": 0.30,
            "filename": 0.25,
            "folder": 0.20,
            "heading": 0.15,
            "body": 0.05,
        },
    },
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
# Global index
# ──────────────────────────────────────────────

_RAG_INIT_ERROR = ""
try:
    _init_supabase_storage()
    chunks = load_chunks()
except Exception as exc:
    _RAG_INIT_ERROR = str(exc)
    if _RAG_DEBUG:
        print(f"[RAG_DEBUG] initial index load failed: {exc}")
    chunks = []
retriever = Retriever(chunks)
load_settings()  # apply settings.json after retriever is ready


def refresh_index(force: bool = False) -> dict | None:
    global chunks, retriever
    chunks = load_chunks()
    retriever = Retriever(chunks)
    _apply_settings_to_runtime()  # re-apply BM25 params to the new retriever
    try:
        return sync_vector_index(force=force)
    except Exception as exc:
        if _RAG_DEBUG:
            print(f"[RAG_DEBUG] vector index sync failed: {exc}")
        return {"ok": False, "error": str(exc), "chunks": len(chunks)}


def _chunk_embedding_payload(chunk: Chunk, embedding: list[float], body_hash: str) -> dict:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id or _stable_document_id(chunk.source),
        "source": chunk.source,
        "title": chunk.title,
        "filename": chunk.filename or chunk.source.rsplit("/", 1)[-1],
        "folder": chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else ""),
        "heading": chunk.heading or chunk.title,
        "body": chunk.text,
        "normalized_body": chunk.normalized_body or normalize_search_text(chunk.text),
        "compact_body": chunk.compact_body or compact_search_text(chunk.text),
        "body_hash": body_hash,
        "embedding": embedding,
        "updated_at": chunk.updated_at,
    }


def sync_vector_index(force: bool = False) -> dict:
    """Persist current chunks and embeddings into the Supabase pgvector table."""
    if not SUPABASE_ENABLED:
        return {"ok": False, "reason": "supabase disabled", "chunks": len(chunks)}
    existing = _db_existing_chunk_hashes()
    valid_ids = [chunk.chunk_id for chunk in chunks if chunk.chunk_id]
    stale_deleted = _db_delete_stale_chunks(valid_ids)
    rows: list[dict] = []
    skipped_no_embedding = 0
    for idx, chunk in enumerate(chunks):
        if not chunk.chunk_id:
            continue
        content = retriever.embedding_store.chunk_embedding_text(chunk)
        body_hash = retriever.embedding_store.text_hash(content)
        if not force and existing.get(chunk.chunk_id) == body_hash:
            continue
        if force:
            embedding = retriever.embedding_store.get_chunk_embedding(chunk, force=True)
            if idx < len(retriever.embeddings):
                retriever.embeddings[idx] = embedding
        else:
            embedding = retriever.embeddings[idx] if idx < len(retriever.embeddings) else []
            if not embedding:
                embedding = retriever.embedding_store.get_chunk_embedding(chunk)
                if idx < len(retriever.embeddings):
                    retriever.embeddings[idx] = embedding
        if not embedding:
            skipped_no_embedding += 1
            continue
        rows.append(_chunk_embedding_payload(chunk, embedding, body_hash))
    if force:
        retriever.embedding_store.save()
    upserted = _db_upsert_search_chunks(rows)
    return {
        "ok": True,
        "chunks": len(chunks),
        "upserted": upserted,
        "stale_deleted": stale_deleted,
        "skipped_no_embedding": skipped_no_embedding,
        "force": force,
    }


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


def search_documents(query: str, top_k: int = 5, debug: bool = False, mode: str = "hybrid") -> list[dict] | dict:
    """Return document-level grouped hybrid search results with score details."""
    query = query.strip()
    if not query:
        return {"results": [], "debug": {}} if debug else []
    candidate_top_k = max(top_k * 4, top_k)
    intent = detect_intent(query)
    candidate_k = INTENT_CONFIG[intent]["candidate_k"]
    chunk_results = retriever.search(query, top_k=candidate_top_k, candidate_k=candidate_k, debug=debug or _RAG_DEBUG, mode=mode)

    grouped: dict[str, dict] = {}
    for chunk, score in chunk_results:
        document_id = chunk.document_id or _stable_document_id(chunk.source)
        detail = retriever.last_score_details.get(chunk.chunk_id or "", {})
        item = {
            "chunk_id": chunk.chunk_id,
            "heading": chunk.heading or chunk.title,
            "matched_text": re.sub(r"\s+", " ", chunk.text).strip()[:700],
            "score": round(score, 4),
            "score_detail": detail,
        }
        if document_id not in grouped:
            grouped[document_id] = {
                "document_id": document_id,
                "title": chunk.title,
                "filename": chunk.filename or chunk.source.rsplit("/", 1)[-1],
                "folder": chunk.folder if chunk.folder is not None else (chunk.source.rsplit("/", 1)[0] if "/" in chunk.source else ""),
                "source": chunk.source,
                "matched_heading": chunk.heading or chunk.title,
                "matched_text": item["matched_text"],
                "snippet": item["matched_text"],
                "score": round(score, 4),
                "score_detail": detail,
                "related_chunks": [],
            }
        else:
            grouped[document_id]["related_chunks"].append(item)

    results = sorted(grouped.values(), key=lambda item: item["score"], reverse=True)[:top_k]
    if not debug:
        return results
    return {
        "results": results,
        "debug": {
            **retriever.last_debug,
            "returned_document_count": len(results),
            "top_scores": [
                {
                    "document_id": item["document_id"],
                    "title": item["title"],
                    "final_score": item["score"],
                    "score_detail": item["score_detail"],
                }
                for item in results
            ],
        },
    }


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
    focused_results = [(chunk, score) for chunk, score in results if not is_low_value_context_title(chunk.title)]
    if focused_results:
        results = focused_results
    if results:
        best_score = results[0][1]
        score_floor = best_score * 0.25
        close_results = [(chunk, score) for chunk, score in results if score >= score_floor]
        if close_results:
            results = close_results
    context = build_compact_context(query, results, max_chars=max_chars, snippets_per_chunk=snippets_per_chunk)

    if _RAG_DEBUG:
        print(f"[RAG_DEBUG] compact context length={len(context)}")

    return results, context


# ──────────────────────────────────────────────
# Answer functions
# ──────────────────────────────────────────────


def immediate_answer_with_sources(query: str, top_k: int) -> tuple[str, list[tuple[Chunk, float]]]:
    query = query.strip()
    if not query:
        return "질문을 입력해 주세요.", []

    results, context = retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요.", results

    return source_based_answer(query, results), results


def llm_answer_with_sources(query: str, top_k: int) -> tuple[str, list[tuple[Chunk, float]]]:
    results, context = retrieve_for_llm(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 오류명, 서버/계정/작업명을 포함해 다시 질문해 주세요.", results

    prompt = _build_llm_user_prompt(query, context)
    llm = get_llm()
    generated = llm.generate(prompt)
    if not generated:
        generated = source_based_answer(query, results)

    sources = "\n".join(
        f"- `{chunk.source}` / {chunk.title} / score={score:.3f}"
        for chunk, score in results
    )
    return f"{generated}\n\n---\n참고 문서:\n{sources}", results


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
