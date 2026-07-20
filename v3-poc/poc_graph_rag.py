#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HK-maintenance v3 PoC — 결정론적 엔티티 그래프 + 그래프 확장 검색

목적
----
"벡터로 시드를 찾고, 그래프로 이웃을 끌어온다"(Neo4j VectorCypherRetriever 패턴)를
PostgreSQL 재귀 CTE로 구현하기 전에, 실제 코퍼스로 타당성을 검증하는 프로토타입.

의도적 제약 (PoC이므로)
----------------------
- SQLite 사용 (Postgres 없이 어디서나 실행). 프로덕션은 Postgres + pgvector
- 임베딩 없이 BM25 + 그래프만으로 검증 (GPU/모델 다운로드 불필요, 망분리 환경에서도 실행)
  → 임베딩의 기여도는 별도 측정. 여기서 검증하려는 것은 "그래프 확장이 recall을 올리는가"
- kiwipiepy 있으면 사용, 없으면 정규식 폴백

검증하려는 가설
--------------
H1. 코퍼스에서 결정론적 엔티티(고객사/시스템/개념)를 규칙만으로 충분히 추출할 수 있다
H2. 그래프 1~2홉 확장이 렉시컬 검색 단독 대비 recall을 올린다
H3. 확장 대상 엣지를 의도별로 제한하지 않으면 노이즈가 급증한다

사용법
------
    python poc_graph_rag.py build   --corpus <경로>     # 그래프 + 인덱스 구축
    python poc_graph_rag.py stats                        # 그래프 통계
    python poc_graph_rag.py search  "질의"               # 검색 (렉시컬 vs +그래프 비교)
    python poc_graph_rag.py eval    --cases <json>       # 평가셋 실행
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# 기본 DB 경로는 임시 디렉터리. 네트워크 마운트에서 SQLite 락이 실패할 수 있고,
# 저장소에 바이너리 산출물을 남기지 않기 위함. --db 로 재지정 가능.
DB_PATH = Path(os.environ.get("POC_DB", Path(tempfile.gettempdir()) / "hk_poc_graph.sqlite3"))

# ---------------------------------------------------------------------------
# 형태소 분석 (kiwipiepy 우선, 없으면 폴백)
# ---------------------------------------------------------------------------

_KIWI = None
_KIWI_TRIED = False

# 색인 대상 품사: 일반명사, 고유명사, 외국어, 영문, 숫자, 어근
_KIWI_POS = {"NNG", "NNP", "SL", "SH", "SN", "XR"}


def _get_kiwi():
    global _KIWI, _KIWI_TRIED
    if _KIWI_TRIED:
        return _KIWI
    _KIWI_TRIED = True
    try:
        from kiwipiepy import Kiwi  # type: ignore

        _KIWI = Kiwi()
        # 도메인 사용자 사전 (프로덕션에서는 DB/파일로 관리)
        for word in DOMAIN_VOCAB:
            try:
                _KIWI.add_user_word(word, "NNP")
            except Exception:
                pass
    except Exception:
        _KIWI = None
    return _KIWI


_TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z][A-Za-z0-9_.-]*|\d+")
_KO_STOP = {
    "그리고", "하지만", "그러나", "또한", "있습니다", "합니다", "입니다", "때문",
    "경우", "관련", "대한", "위한", "통해", "이후", "이전", "내용", "확인", "가능",
    "사용", "진행", "처리", "필요", "이때", "해당", "다음", "아래", "위의",
}


def tokenize(text: str) -> list[str]:
    """표제어 토큰화. 프로덕션에서는 결과를 chunks_v3.lemmas 컬럼에 저장."""
    kiwi = _get_kiwi()
    if kiwi is not None:
        out = []
        for tok in kiwi.tokenize(text):
            if tok.tag in _KIWI_POS and len(tok.form) > 1:
                out.append(tok.form.lower())
        if out:
            return [t for t in out if t not in _KO_STOP]
    # 폴백: 정규식 + 한글 2/3-gram
    raw = _TOKEN_RE.findall(text.lower())
    out = []
    for t in raw:
        if len(t) < 2 or t in _KO_STOP:
            continue
        out.append(t)
        if re.fullmatch(r"[가-힣]+", t) and len(t) > 3:
            out.extend(t[i:i + 2] for i in range(len(t) - 1))
    return out


# ---------------------------------------------------------------------------
# 도메인 사전 (규칙 기반 엔티티 추출의 핵심 자산)
#   프로덕션에서는 graph_nodes / graph_node_aliases 테이블로 관리하고
#   관리자 UI에서 편집 가능해야 함. 여기 하드코딩은 PoC 한정.
#   초기 시드는 Soynlp 코퍼스 마이닝 + 유지보수팀 검수로 확보 권장.
# ---------------------------------------------------------------------------

SYSTEM_TERMS: dict[str, list[str]] = {
    "홈페이지": ["홈페이지", "웹사이트", "웹 사이트", "website", "사이트"],
    "그룹웨어": ["그룹웨어", "groupware"],
    "게시판": ["게시판", "bbs", "board"],
    "회원관리": ["회원관리", "회원 관리", "멤버십", "회원가입"],
    "결제시스템": ["결제", "결재시스템", "pg", "payment", "이니시스", "kcp", "나이스페이"],
    "메일": ["메일", "이메일", "smtp", "mail", "메일서버"],
    "DB": ["데이터베이스", "database", "mysql", "mariadb", "oracle", "postgres", "mssql", "db"],
    "WAS": ["was", "톰캣", "tomcat", "jboss", "웹로직", "weblogic", "아파치", "apache", "nginx"],
    "SSL인증서": ["ssl", "인증서", "https", "tls", "certificate"],
    "도메인": ["도메인", "domain", "dns", "네임서버"],
    "호스팅": ["호스팅", "hosting", "서버호스팅", "웹호스팅", "클라우드"],
    "백업": ["백업", "backup", "복구", "restore"],
    "모바일앱": ["앱", "app", "안드로이드", "android", "ios", "모바일"],
    "관리자페이지": ["관리자", "admin", "어드민", "백오피스"],
    "검색": ["검색엔진", "검색 기능", "elasticsearch"],
    "SMS": ["sms", "문자", "알림톡", "카카오톡"],
    "보안": ["보안", "취약점", "해킹", "방화벽", "waf", "security"],
    "학회관리": ["학회", "초록", "논문", "심사", "학술대회"],
    "예약": ["예약", "booking", "reservation"],
    "설문": ["설문", "survey", "폼"],
}

ISSUE_TERMS: dict[str, list[str]] = {
    "장애": ["장애", "다운", "먹통", "접속불가", "에러", "오류", "error", "실패"],
    "성능": ["느림", "지연", "속도", "타임아웃", "timeout", "부하"],
    "갱신": ["갱신", "만료", "연장", "renewal", "expire"],
    "기능개선": ["개선", "수정", "요청", "추가", "변경", "리뉴얼"],
    "이관": ["이관", "이전", "마이그레이션", "migration", "이사"],
    "복구": ["복구", "롤백", "restore", "재기동", "재시작"],
}

# kiwipiepy 사용자 사전에 등록할 도메인 어휘
DOMAIN_VOCAB: list[str] = sorted(
    {k for k in SYSTEM_TERMS} | {v for vs in SYSTEM_TERMS.values() for v in vs if len(v) > 1}
)

# 기존 backend/rag.py:47-56 의 QUERY_ALIASES 하드코딩을 이관한 형태.
# 프로덕션에서는 graph_node_aliases 테이블.
CUSTOMER_ALIASES: dict[str, list[str]] = {
    "시도지사협의회": ["시도지사", "시도지사협의회", "대한시도지사협회"],
    "KB손보CNS": ["kb손보", "kb손해보험", "손보cns", "kb"],
    "성의교정_카톨릭대학교": ["가톨릭대", "카톨릭대", "성의교정"],
    "유투바이오": ["유투바이오", "u2bio"],
    "코웨이": ["코웨이", "coway"],
    "대한항공": ["대한항공", "korean air", "kal"],
}


# ---------------------------------------------------------------------------
# 청킹 (진단 리포트 §2.4: 하드코딩 섹션 스킵 리스트를 제거한 버전)
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    customer: str
    doc_title: str
    heading_path: list[str]
    body: str
    ordinal: int


def split_markdown(text: str, *, doc_id: str, customer: str, doc_title: str,
                   max_chars: int = 1200, overlap: int = 150) -> list[Chunk]:
    """헤딩 계층을 보존하는 청킹.

    현행 v1(rag.py:313-328)과의 차이:
      - 섹션 제목 스킵 리스트 없음 (콘텐츠를 버리지 않음)
      - heading_path 를 보존해 그래프 노드/컨텍스트에 활용
      - 최소 길이 컷을 80 -> 40 자로 완화 (짧은 표/목록 보존)
    """
    sections: list[tuple[list[str], list[str]]] = []
    stack: list[str] = []
    buf: list[str] = []

    def flush():
        if buf and any(line.strip() for line in buf):
            sections.append((list(stack), list(buf)))
        buf.clear()

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            del stack[level - 1:]
            while len(stack) < level - 1:
                stack.append("")
            stack.append(title)
        else:
            buf.append(line)
    flush()

    chunks: list[Chunk] = []
    ordinal = 0
    for path, lines in sections:
        body = "\n".join(lines).strip()
        if len(body) < 40:
            continue
        # 긴 섹션은 슬라이딩 윈도우로 분할
        start = 0
        while start < len(body):
            part = body[start:start + max_chars]
            if len(part) >= 40:
                chunks.append(Chunk(
                    chunk_id=f"{doc_id}_c{ordinal:04d}",
                    document_id=doc_id,
                    customer=customer,
                    doc_title=doc_title,
                    heading_path=[p for p in path if p],
                    body=part,
                    ordinal=ordinal,
                ))
                ordinal += 1
            if start + max_chars >= len(body):
                break
            start += max_chars - overlap
    return chunks


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id     TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL,
    customer     TEXT,
    doc_title    TEXT,
    heading_path TEXT,
    body         TEXT NOT NULL,
    lemmas       TEXT NOT NULL,
    ordinal      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_cust ON chunks(customer);

-- 역색인 (프로덕션에서는 Postgres tsvector + GIN 으로 대체)
CREATE TABLE IF NOT EXISTS postings (
    term     TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    tf       INTEGER NOT NULL,
    PRIMARY KEY (term, chunk_id)
);
CREATE INDEX IF NOT EXISTS idx_postings_term ON postings(term);

CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type   TEXT NOT NULL,
    natural_key TEXT NOT NULL,
    label       TEXT NOT NULL,
    customer    TEXT,
    confidence  REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL,
    UNIQUE (node_type, natural_key)
);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON graph_nodes(node_type);

CREATE TABLE IF NOT EXISTS graph_node_aliases (
    alias   TEXT NOT NULL,
    node_id INTEGER NOT NULL,
    weight  REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (alias, node_id)
);
CREATE INDEX IF NOT EXISTS idx_alias ON graph_node_aliases(alias);

CREATE TABLE IF NOT EXISTS graph_edges (
    src_id     INTEGER NOT NULL,
    dst_id     INTEGER NOT NULL,
    edge_type  TEXT NOT NULL,
    weight     REAL NOT NULL DEFAULT 1.0,
    -- 허브 페널티가 반영된 확장 가중치. weight / (1 + ln(dst 차수))
    -- 'SSL인증서'처럼 수백 청크에 연결된 허브를 경유한 확장은 정보량이 낮으므로
    -- IDF 와 동일한 발상으로 감쇠시킨다. (PoC 실험 결과 §H3 참조)
    exp_weight REAL NOT NULL DEFAULT 1.0,
    confidence REAL NOT NULL DEFAULT 1.0,
    source     TEXT NOT NULL,
    PRIMARY KEY (src_id, dst_id, edge_type)
);
CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(src_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON graph_edges(dst_id, edge_type);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------------------
# 그래프 구축
# ---------------------------------------------------------------------------

class GraphBuilder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._node_cache: dict[tuple[str, str], int] = {}

    def node(self, node_type: str, natural_key: str, label: str | None = None,
             *, customer: str | None = None, confidence: float = 1.0,
             source: str = "rule") -> int:
        key = (node_type, natural_key)
        if key in self._node_cache:
            return self._node_cache[key]
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO graph_nodes(node_type, natural_key, label, customer, confidence, source)"
            " VALUES (?,?,?,?,?,?)",
            (node_type, natural_key, label or natural_key, customer, confidence, source),
        )
        if cur.lastrowid:
            node_id = cur.lastrowid
        else:
            row = self.conn.execute(
                "SELECT node_id FROM graph_nodes WHERE node_type=? AND natural_key=?",
                (node_type, natural_key)).fetchone()
            node_id = row["node_id"]
        self._node_cache[key] = node_id
        return node_id

    def alias(self, node_id: int, alias: str, weight: float = 1.0) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO graph_node_aliases(alias, node_id, weight) VALUES (?,?,?)",
            (alias.lower(), node_id, weight))

    def edge(self, src: int, dst: int, edge_type: str, *, weight: float = 1.0,
             confidence: float = 1.0, source: str = "rule") -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO graph_edges(src_id, dst_id, edge_type, weight, confidence, source)"
            " VALUES (?,?,?,?,?,?)",
            (src, dst, edge_type, weight, confidence, source))

    def biedge(self, a: int, b: int, edge_type: str, **kw) -> None:
        self.edge(a, b, edge_type, **kw)
        self.edge(b, a, edge_type, **kw)


def extract_entities(text: str) -> tuple[set[str], set[str]]:
    """규칙 기반 엔티티 추출. 반환: (시스템 집합, 이슈유형 집합)

    LLM 미사용 = 100% 재현 가능, 재인덱싱 비용 0, 추출률 검증 가능.
    문헌상 LLM 추출 그래프는 정답 엔티티의 ~65%만 포착(arXiv 2502.11371).
    여기서는 사전에 있는 것은 100% 포착되며, 누락은 사전 확충으로 해결 가능.
    """
    low = text.lower()
    systems = {canon for canon, variants in SYSTEM_TERMS.items()
               if any(v in low for v in variants)}
    issues = {canon for canon, variants in ISSUE_TERMS.items()
              if any(v in low for v in variants)}
    return systems, issues


def build(corpus_dir: Path, db_path: Path = DB_PATH) -> None:
    if db_path.exists():
        db_path.unlink()
        for suf in ("-wal", "-shm"):
            p = Path(str(db_path) + suf)
            if p.exists():
                p.unlink()

    conn = connect(db_path)
    gb = GraphBuilder(conn)

    md_files = sorted(p for p in corpus_dir.rglob("*.md"))
    print(f"[build] 문서 {len(md_files)}개 발견 — {corpus_dir}")

    all_chunks: list[Chunk] = []
    doc_count = 0

    for path in md_files:
        rel = path.relative_to(corpus_dir)
        # 폴더 = 고객사 (진단 리포트 §3.2: 이미 존재하는 결정론적 엔티티)
        customer = rel.parts[0] if len(rel.parts) > 1 else "_공통"
        if customer.endswith(".md"):
            customer = "_공통"
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover
            print(f"  ! 읽기 실패 {rel}: {exc}", file=sys.stderr)
            continue

        doc_id = re.sub(r"[^0-9A-Za-z가-힣]+", "_", str(rel.with_suffix("")))[:120]
        doc_title = path.stem

        cust_node = gb.node("Customer", customer, customer, customer=customer,
                            source="folder")
        for al in CUSTOMER_ALIASES.get(customer, [customer]):
            gb.alias(cust_node, al)
        gb.alias(cust_node, customer)

        doc_node = gb.node("Document", doc_id, doc_title, customer=customer,
                           source="relational")
        gb.edge(doc_node, cust_node, "BELONGS_TO", source="folder")
        gb.edge(cust_node, doc_node, "HAS_DOCUMENT", source="folder")

        chunks = split_markdown(text, doc_id=doc_id, customer=customer,
                                doc_title=doc_title)
        if not chunks:
            continue
        doc_count += 1

        for ch in chunks:
            ch_node = gb.node("Chunk", ch.chunk_id, ch.doc_title, customer=customer,
                              source="relational")
            gb.edge(doc_node, ch_node, "HAS_CHUNK", source="chunking")
            gb.edge(ch_node, doc_node, "PART_OF", source="chunking")
            gb.edge(ch_node, cust_node, "BELONGS_TO", source="folder")

            scope = ch.body + " " + " ".join(ch.heading_path) + " " + ch.doc_title
            systems, issues = extract_entities(scope)

            for sysname in systems:
                s_node = gb.node("System", sysname, sysname, source="rule",
                                 confidence=0.9)
                gb.edge(ch_node, s_node, "MENTIONS", weight=0.9, source="rule")
                gb.edge(s_node, ch_node, "MENTIONED_IN", weight=0.9, source="rule")
                # 고객사가 어떤 시스템을 보유하는지 (집계로 추론)
                gb.edge(cust_node, s_node, "OWNS", weight=0.7, source="rule",
                        confidence=0.7)
                gb.edge(s_node, cust_node, "OWNED_BY", weight=0.7, source="rule",
                        confidence=0.7)
                for v in SYSTEM_TERMS[sysname]:
                    gb.alias(s_node, v)

            for issue in issues:
                i_node = gb.node("IssueType", issue, issue, source="rule",
                                 confidence=0.8)
                gb.edge(ch_node, i_node, "HAS_ISSUE", weight=0.8, source="rule")
                gb.edge(i_node, ch_node, "OCCURS_IN", weight=0.8, source="rule")
                for v in ISSUE_TERMS[issue]:
                    gb.alias(i_node, v)

        all_chunks.extend(chunks)

    # 청크 + 역색인 적재
    print(f"[build] 청크 {len(all_chunks)}개 생성 (문서 {doc_count}개)")
    for ch in all_chunks:
        lemmas = tokenize(ch.body + " " + " ".join(ch.heading_path) + " " + ch.doc_title)
        conn.execute(
            "INSERT OR REPLACE INTO chunks"
            "(chunk_id, document_id, customer, doc_title, heading_path, body, lemmas, ordinal)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (ch.chunk_id, ch.document_id, ch.customer, ch.doc_title,
             json.dumps(ch.heading_path, ensure_ascii=False), ch.body,
             " ".join(lemmas), ch.ordinal))
        for term, tf in Counter(lemmas).items():
            conn.execute(
                "INSERT OR REPLACE INTO postings(term, chunk_id, tf) VALUES (?,?,?)",
                (term, ch.chunk_id, tf))

    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('n_chunks', ?)",
                 (str(len(all_chunks)),))
    avg_len = sum(len(c.body) for c in all_chunks) / max(1, len(all_chunks))
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES ('avg_len', ?)",
                 (str(avg_len),))
    conn.commit()

    # 청크 간 개념 공유 기반 SIMILAR_TO 엣지 (임베딩 없이 근사)
    _build_similarity_edges(conn, gb)
    conn.commit()
    _compute_hub_penalty(conn)
    conn.commit()
    print(f"[build] 완료 → {db_path}")
    stats(conn)


def _compute_hub_penalty(conn: sqlite3.Connection) -> None:
    """허브 노드 경유 확장을 감쇠시키는 exp_weight 계산.

    PoC 실험에서 확인된 문제(가설 H3):
      'SSL인증서' 같은 엔티티가 700개 청크에 연결되면, 이를 경유한 2홉 확장이
      코퍼스 전체를 끌어와 렉시컬 결과를 희석시킨다. 그래프가 도움이 되기는커녕
      노이즈원이 된다.
    해결: 엔티티의 차수(degree)에 로그 역비례하는 페널티. IDF와 동일한 발상.
    """
    conn.execute("""
        UPDATE graph_edges
        SET exp_weight = weight / (1.0 + 0.9 * (
            SELECT CASE WHEN COUNT(*) <= 1 THEN 0.0
                        ELSE LOG(CAST(COUNT(*) AS REAL)) END
            FROM graph_edges e2 WHERE e2.src_id = graph_edges.dst_id
        ))
    """)
    row = conn.execute(
        "SELECT MIN(exp_weight) mn, MAX(exp_weight) mx, AVG(exp_weight) av "
        "FROM graph_edges").fetchone()
    print(f"[build] 허브 페널티 적용: exp_weight "
          f"min={row['mn']:.4f} max={row['mx']:.4f} avg={row['av']:.4f}")


def _build_similarity_edges(conn: sqlite3.Connection, gb: GraphBuilder,
                            min_shared: int = 2, max_per_node: int = 5) -> None:
    """같은 System/IssueType 을 여러 개 공유하는 청크를 연결.

    프로덕션에서는 임베딩 코사인 유사도로 대체 (더 정확).
    여기서는 임베딩 없이 그래프 확장 효과만 분리 측정하기 위한 근사.
    """
    rows = conn.execute(
        "SELECT e.src_id AS chunk_id, e.dst_id AS ent_id "
        "FROM graph_edges e JOIN graph_nodes n ON n.node_id = e.dst_id "
        "WHERE e.edge_type IN ('MENTIONS','HAS_ISSUE') AND n.node_type IN ('System','IssueType')"
    ).fetchall()
    by_chunk: dict[int, set[int]] = defaultdict(set)
    for r in rows:
        by_chunk[r["chunk_id"]].add(r["ent_id"])

    by_ent: dict[int, set[int]] = defaultdict(set)
    for c, ents in by_chunk.items():
        for e in ents:
            by_ent[e].add(c)

    added = 0
    for chunk, ents in by_chunk.items():
        cand: Counter[int] = Counter()
        for e in ents:
            # 너무 흔한 엔티티는 제외 (허브 노드가 그래프를 오염시킴)
            if len(by_ent[e]) > 60:
                continue
            for other in by_ent[e]:
                if other != chunk:
                    cand[other] += 1
        for other, shared in cand.most_common(max_per_node):
            if shared < min_shared:
                break
            gb.edge(chunk, other, "SIMILAR_TO",
                    weight=min(1.0, shared / 4.0), source="cooccurrence",
                    confidence=0.6)
            added += 1
    print(f"[build] SIMILAR_TO 엣지 {added}개 생성")


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------

# 진단 리포트 §4.2: 의도별 엣지 화이트리스트.
# 무제한 확장은 노이즈를 폭증시키므로 반드시 제한한다 (가설 H3).
INTENT_EDGES: dict[str, tuple[str, ...]] = {
    "customer_info": ("BELONGS_TO", "HAS_DOCUMENT", "HAS_CHUNK", "OWNS", "MENTIONED_IN"),
    "history":       ("SIMILAR_TO", "OCCURS_IN", "HAS_ISSUE", "MENTIONED_IN"),
    "manual":        ("MENTIONED_IN", "HAS_CHUNK", "SIMILAR_TO"),
    "default":       ("MENTIONED_IN", "HAS_CHUNK", "SIMILAR_TO", "OWNS"),
}


@dataclass
class Hit:
    chunk_id: str
    score: float
    doc_title: str = ""
    customer: str = ""
    via: str = ""
    ranks: dict[str, int] = field(default_factory=dict)


class Searcher:
    K1 = 1.2
    B = 0.75

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.n_chunks = int(self._meta("n_chunks", "1"))
        self.avg_len = float(self._meta("avg_len", "1000")) / 3.0  # 대략 토큰 수

    def _meta(self, k: str, default: str) -> str:
        row = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return row["v"] if row else default

    # -- 1차 검색: 렉시컬 (BM25) ------------------------------------------
    def lexical(self, query: str, limit: int = 30) -> list[Hit]:
        terms = tokenize(query)
        if not terms:
            return []
        scores: dict[str, float] = defaultdict(float)
        doc_len: dict[str, int] = {}

        for term in set(terms):
            rows = self.conn.execute(
                "SELECT p.chunk_id, p.tf, LENGTH(c.lemmas) AS dl "
                "FROM postings p JOIN chunks c ON c.chunk_id = p.chunk_id "
                "WHERE p.term = ?", (term,)).fetchall()
            df = len(rows)
            if df == 0:
                continue
            idf = math.log(1 + (self.n_chunks - df + 0.5) / (df + 0.5))
            for r in rows:
                dl = r["dl"] / 3.0
                doc_len[r["chunk_id"]] = dl
                tf = r["tf"]
                denom = tf + self.K1 * (1 - self.B + self.B * dl / max(1.0, self.avg_len))
                scores[r["chunk_id"]] += idf * (tf * (self.K1 + 1)) / denom

        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [Hit(chunk_id=cid, score=sc, via="lexical") for cid, sc in ranked]

    # -- 엔티티 링킹 -------------------------------------------------------
    def link_entities(self, query: str) -> list[sqlite3.Row]:
        low = query.lower()
        found: dict[int, sqlite3.Row] = {}
        for row in self.conn.execute(
                "SELECT a.alias, a.node_id, n.node_type, n.label "
                "FROM graph_node_aliases a JOIN graph_nodes n ON n.node_id = a.node_id"):
            if row["alias"] and row["alias"] in low:
                found[row["node_id"]] = row
        return list(found.values())

    def detect_intent(self, query: str, linked: Sequence[sqlite3.Row]) -> str:
        types = {r["node_type"] for r in linked}
        low = query.lower()
        if any(w in low for w in ("이력", "사례", "이전에", "과거", "비슷한", "유사")):
            return "history"
        if "Customer" in types:
            return "customer_info"
        if any(w in low for w in ("어떻게", "방법", "절차", "설정", "매뉴얼")):
            return "manual"
        return "default"

    # -- 1차 검색: 그래프 확장 --------------------------------------------
    def graph_expand(self, seed_node_ids: Sequence[int], edge_types: Sequence[str],
                     *, max_hop: int = 2, decay: float = 0.6,
                     min_score: float = 0.05, limit: int = 30) -> list[Hit]:
        """SQLite 재귀 CTE. Postgres 이식 시 거의 그대로 사용 가능.

        기획서 §4.2 의 쿼리와 동일 구조.
        """
        if not seed_node_ids:
            return []
        seed_ph = ",".join("?" * len(seed_node_ids))
        edge_ph = ",".join("?" * len(edge_types))
        sql = f"""
        WITH RECURSIVE walk(node_id, hop, decay) AS (
            SELECT node_id, 0, 1.0 FROM graph_nodes WHERE node_id IN ({seed_ph})
          UNION ALL
            SELECT e.dst_id, w.hop + 1, w.decay * e.exp_weight * ?
            FROM walk w JOIN graph_edges e ON e.src_id = w.node_id
            WHERE w.hop < ?
              AND e.edge_type IN ({edge_ph})
              AND w.decay * e.exp_weight * ? > ?
        ),
        reached AS (
            SELECT node_id, MAX(decay) AS score, MIN(hop) AS hop
            FROM walk WHERE hop > 0 GROUP BY node_id
        )
        SELECT c.chunk_id, c.doc_title, c.customer, r.score, r.hop
        FROM reached r
        JOIN graph_nodes n ON n.node_id = r.node_id AND n.node_type = 'Chunk'
        JOIN chunks c ON c.chunk_id = n.natural_key
        ORDER BY r.score DESC LIMIT ?
        """
        params = [*seed_node_ids, decay, max_hop, *edge_types, decay, min_score, limit]
        rows = self.conn.execute(sql, params).fetchall()
        return [Hit(chunk_id=r["chunk_id"], score=r["score"], doc_title=r["doc_title"],
                    customer=r["customer"], via=f"graph:{r['hop']}hop") for r in rows]

    # -- RRF 융합 ----------------------------------------------------------
    @staticmethod
    def rrf(runs: dict[str, list[Hit]], *, k: int = 60,
            weights: dict[str, float] | None = None) -> list[Hit]:
        """Reciprocal Rank Fusion.

        진단 리포트 §P1: 현행 고정 선형 가중치는 BM25 점수/코사인/ILIKE 매칭수의
        스케일이 달라 합산 의미가 불분명. RRF는 순위만 쓰므로 스케일 문제가 없음.
        """
        weights = weights or {}
        acc: dict[str, float] = defaultdict(float)
        meta: dict[str, Hit] = {}
        rank_map: dict[str, dict[str, int]] = defaultdict(dict)
        for name, hits in runs.items():
            w = weights.get(name, 1.0)
            for rank, h in enumerate(hits, start=1):
                acc[h.chunk_id] += w / (k + rank)
                rank_map[h.chunk_id][name] = rank
                meta.setdefault(h.chunk_id, h)
        out = []
        for cid, score in sorted(acc.items(), key=lambda kv: -kv[1]):
            base = meta[cid]
            out.append(Hit(chunk_id=cid, score=score, doc_title=base.doc_title,
                           customer=base.customer,
                           via="+".join(sorted(rank_map[cid])),
                           ranks=rank_map[cid]))
        return out

    def _hydrate(self, hits: list[Hit]) -> list[Hit]:
        for h in hits:
            if h.doc_title:
                continue
            row = self.conn.execute(
                "SELECT doc_title, customer FROM chunks WHERE chunk_id=?",
                (h.chunk_id,)).fetchone()
            if row:
                h.doc_title = row["doc_title"]
                h.customer = row["customer"]
        return hits

    # -- 통합 검색 ---------------------------------------------------------
    def search(self, query: str, *, use_graph: bool = True, limit: int = 10
               ) -> tuple[list[Hit], dict]:
        lex = self._hydrate(self.lexical(query, limit=30))
        debug = {"n_lexical": len(lex)}

        if not use_graph:
            return lex[:limit], debug

        linked = self.link_entities(query)
        intent = self.detect_intent(query, linked)
        edge_types = INTENT_EDGES[intent]
        debug.update({
            "linked_entities": [f"{r['node_type']}:{r['label']}" for r in linked],
            "intent": intent,
            "edge_types": list(edge_types),
        })

        # 시드 = 링킹된 엔티티 노드 + 렉시컬 상위 5개 청크 노드
        seeds = [r["node_id"] for r in linked]
        for h in lex[:5]:
            row = self.conn.execute(
                "SELECT node_id FROM graph_nodes WHERE node_type='Chunk' AND natural_key=?",
                (h.chunk_id,)).fetchone()
            if row:
                seeds.append(row["node_id"])

        gr = self.graph_expand(seeds, edge_types, limit=30)
        debug["n_graph"] = len(gr)
        debug["n_seeds"] = len(seeds)

        runs = {"lexical": lex, "graph": gr}
        weights = {"lexical": 1.0, "graph": 0.6}

        # 고객사 스코핑: 질의에 고객사가 명시되면 그 고객사 문서를 별도 런으로 추가.
        # 유지보수 도메인에서는 "어느 고객사인가"가 거의 항상 1차 필터이므로
        # 이 신호를 그래프 확장 점수에 묻히게 두면 안 된다.
        customers = [r["label"] for r in linked if r["node_type"] == "Customer"]
        if customers:
            debug["customer_scope"] = customers
            scoped = self._customer_scoped(args_query=query, customers=customers,
                                           lexical=lex, limit=20)
            runs["customer"] = scoped
            weights["customer"] = 1.2

        fused = self.rrf(runs, weights=weights)
        return self._hydrate(fused[:limit]), debug

    def _customer_scoped(self, *, args_query: str, customers: Sequence[str],
                         lexical: Sequence[Hit], limit: int = 20) -> list[Hit]:
        """해당 고객사 청크만 대상으로 재순위화한 런.

        프로덕션에서는 이 필터가 RLS(권한)와 별개로 '관련성' 목적으로 동작하며,
        RLS는 그 위에서 항상 강제된다. 둘을 혼동하면 안 된다.
        """
        allowed = set(customers)
        # 원본 Hit 을 변형하지 않도록 복사 (렉시컬 런 오염 방지)
        scoped = [Hit(chunk_id=h.chunk_id, score=h.score, doc_title=h.doc_title,
                      customer=h.customer, via="customer")
                  for h in lexical if h.customer in allowed]
        seen = {h.chunk_id for h in scoped}
        if len(scoped) < limit:
            terms = set(tokenize(args_query))
            ph = ",".join("?" * len(allowed))
            rows = self.conn.execute(
                f"SELECT chunk_id, doc_title, customer, lemmas FROM chunks "
                f"WHERE customer IN ({ph})", tuple(allowed)).fetchall()
            extra = []
            for r in rows:
                if r["chunk_id"] in seen:
                    continue
                overlap = len(terms & set(r["lemmas"].split()))
                if overlap:
                    extra.append(Hit(chunk_id=r["chunk_id"], score=float(overlap),
                                     doc_title=r["doc_title"], customer=r["customer"],
                                     via="customer"))
            extra.sort(key=lambda h: -h.score)
            scoped.extend(extra[: limit - len(scoped)])
        return scoped[:limit]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def stats(conn: sqlite3.Connection) -> None:
    print("\n=== 그래프 통계 ===")
    print(f"{'노드 타입':<14}{'개수':>8}")
    for r in conn.execute(
            "SELECT node_type, COUNT(*) c FROM graph_nodes GROUP BY node_type ORDER BY c DESC"):
        print(f"{r['node_type']:<14}{r['c']:>8}")
    print()
    print(f"{'엣지 타입':<16}{'개수':>8}")
    for r in conn.execute(
            "SELECT edge_type, COUNT(*) c FROM graph_edges GROUP BY edge_type ORDER BY c DESC"):
        print(f"{r['edge_type']:<16}{r['c']:>8}")
    n_nodes = conn.execute("SELECT COUNT(*) c FROM graph_nodes").fetchone()["c"]
    n_edges = conn.execute("SELECT COUNT(*) c FROM graph_edges").fetchone()["c"]
    n_chunks = conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
    n_terms = conn.execute("SELECT COUNT(DISTINCT term) c FROM postings").fetchone()["c"]
    print(f"\n총 노드 {n_nodes} / 엣지 {n_edges} / 청크 {n_chunks} / 고유 표제어 {n_terms}")
    kiwi = "kiwipiepy" if _get_kiwi() is not None else "정규식 폴백(kiwipiepy 미설치)"
    print(f"형태소 분석기: {kiwi}")

    # 엔티티 커버리지 — 가설 H1 검증
    covered = conn.execute(
        "SELECT COUNT(DISTINCT src_id) c FROM graph_edges "
        "WHERE edge_type IN ('MENTIONS','HAS_ISSUE')").fetchone()["c"]
    print(f"엔티티가 1개 이상 연결된 청크: {covered}/{n_chunks} "
          f"({covered / max(1, n_chunks):.1%})  ← 가설 H1 지표")


def cmd_search(args) -> None:
    conn = connect(Path(args.db))
    s = Searcher(conn)

    lex_hits, _ = s.search(args.query, use_graph=False, limit=args.limit)
    gr_hits, debug = s.search(args.query, use_graph=True, limit=args.limit)

    print(f"\n질의: {args.query}")
    print(f"엔티티 링킹: {debug.get('linked_entities') or '없음'}")
    print(f"의도: {debug.get('intent')}  |  허용 엣지: {', '.join(debug.get('edge_types', []))}")
    print(f"시드 {debug.get('n_seeds')}개 → 그래프 도달 청크 {debug.get('n_graph')}개")

    print("\n--- A. 렉시컬 단독 ---")
    for i, h in enumerate(lex_hits, 1):
        print(f"{i:2}. [{h.customer}] {h.doc_title}  ({h.score:.4f})")

    print("\n--- B. 렉시컬 + 그래프 확장 (RRF) ---")
    lex_ids = {h.chunk_id for h in lex_hits}
    for i, h in enumerate(gr_hits, 1):
        mark = "  " if h.chunk_id in lex_ids else "★ "  # ★ = 그래프가 새로 발굴
        print(f"{mark}{i:2}. [{h.customer}] {h.doc_title}  ({h.score:.4f}, via={h.via})")
    new = [h for h in gr_hits if h.chunk_id not in lex_ids]
    print(f"\n★ 그래프가 새로 끌어온 청크: {len(new)}/{len(gr_hits)}")


def cmd_eval(args) -> None:
    """평가셋 실행. cases.json 형식:
    [{"query": "...", "relevant_docs": ["문서제목1", ...]}, ...]
    """
    conn = connect(Path(args.db))
    s = Searcher(conn)
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))

    results = {"lexical": [], "graph": []}
    for case in cases:
        q = case["query"]
        gold = {g.lower() for g in case.get("relevant_docs", [])}
        if not gold:
            continue
        for mode, use_graph in (("lexical", False), ("graph", True)):
            hits, _ = s.search(q, use_graph=use_graph, limit=10)
            titles = [h.doc_title.lower() for h in hits]
            r5 = any(t in gold for t in titles[:5])
            r10 = any(t in gold for t in titles[:10])
            rank = next((i + 1 for i, t in enumerate(titles) if t in gold), None)
            results[mode].append({"query": q, "r5": r5, "r10": r10, "rank": rank})

    print(f"\n=== 평가 결과 ({len(results['lexical'])}건) ===")
    print(f"{'모드':<12}{'Recall@5':>10}{'Recall@10':>12}{'MRR':>8}")
    for mode, rows in results.items():
        n = len(rows) or 1
        r5 = sum(r["r5"] for r in rows) / n
        r10 = sum(r["r10"] for r in rows) / n
        mrr = sum(1 / r["rank"] for r in rows if r["rank"]) / n
        print(f"{mode:<12}{r5:>10.4f}{r10:>12.4f}{mrr:>8.4f}")

    # 그래프 전용 정답 / 렉시컬 전용 정답 (상보성 측정 — 문헌 §3.1 참고)
    lex_ok = {r["query"] for r in results["lexical"] if r["r5"]}
    gr_ok = {r["query"] for r in results["graph"] if r["r5"]}
    print(f"\n그래프 전용 정답: {len(gr_ok - lex_ok)}건")
    print(f"렉시컬 전용 정답: {len(lex_ok - gr_ok)}건")
    print(f"공통 정답: {len(lex_ok & gr_ok)}건")
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n상세 결과 → {args.out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="HK-maintenance v3 Graph RAG PoC")
    ap.add_argument("--db", default=str(DB_PATH))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="코퍼스에서 그래프+인덱스 구축")
    p.add_argument("--corpus", required=True)

    sub.add_parser("stats", help="그래프 통계")

    p = sub.add_parser("search", help="검색 (렉시컬 vs +그래프 비교)")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("eval", help="평가셋 실행")
    p.add_argument("--cases", required=True)
    p.add_argument("--out", default=None)

    args = ap.parse_args()
    if args.cmd == "build":
        build(Path(args.corpus), Path(args.db))
    elif args.cmd == "stats":
        stats(connect(Path(args.db)))
    elif args.cmd == "search":
        cmd_search(args)
    elif args.cmd == "eval":
        cmd_eval(args)


if __name__ == "__main__":
    main()
