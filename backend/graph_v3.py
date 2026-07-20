"""v3 그래프 레이어 — 운영 코퍼스에서 결정론적 엔티티 그래프를 즉석 생성.

설계 원칙 (docs/v3-planning/02_v3_아키텍처_기획서.md 참조)
------------------------------------------------------
- 스키마 마이그레이션 없음. 기존 문서 레코드만 읽어 메모리에 그래프를 만든다.
  graph_nodes / graph_edges 테이블 도입은 Phase 4 과제이며, 그때 이 모듈의
  build_graph() 결과를 그대로 적재하면 된다.
- LLM 미사용. 폴더=고객사, 파일=문서 라는 100% 정확한 관계 + 사전 기반
  엔티티 매칭만 사용한다. 재현 가능하고 재빌드 비용이 사실상 0이다.
- 허브 페널티 필수. 특정 엔티티가 코퍼스 대부분에 연결되면 이를 경유한
  확장이 전체를 끌어와 검색을 오염시킨다. IDF와 같은 발상으로 감쇠한다.
- 저메모리 전제. Render 512Mi 에서도 동작해야 하므로 본문은 보관하지 않고
  미리보기만 남긴다. 최초 요청 시 지연 빌드하고 지문(fingerprint)으로 무효화한다.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

GRAPH_CACHE_TTL = int(os.getenv("V3_GRAPH_CACHE_TTL", "300"))

# 512Mi 환경 기준 상한. 129문서 기준 그래프가 약 14MB 이므로 1000문서에서
# 약 110MB. 이 이상은 Phase 4 의 graph_nodes/graph_edges 테이블로 가야 한다.
GRAPH_MAX_DOCS = max(1, int(os.getenv("V3_GRAPH_MAX_DOCS", "1000")))

# 직렬화 응답 상한. 인증이 없는 상태에서 코퍼스 전량이 한 번의 요청으로
# 빠져나가는 것을 막는다. (§보안 — Phase 3 인증 도입 전까지의 완화책)
SERIALIZE_MAX_NODES = max(50, int(os.getenv("V3_SERIALIZE_MAX_NODES", "1200")))

CHUNK_MAX_CHARS = max(200, int(os.getenv("V3_CHUNK_MAX_CHARS", "1200")))
# 오버랩이 청크 크기 이상이면 슬라이딩 윈도우의 보폭이 0 이하가 되어
# 무한 루프에 빠진다. 이 루프는 _cache_lock 을 쥔 채 돌기 때문에 프로세스
# 전체(v1 포함)가 멈춘다. 환경변수는 신뢰하지 않고 강제로 잘라낸다.
CHUNK_OVERLAP = min(
    max(0, int(os.getenv("V3_CHUNK_OVERLAP", "150"))),
    CHUNK_MAX_CHARS - 100,
)
CHUNK_MIN_CHARS = max(1, int(os.getenv("V3_CHUNK_MIN_CHARS", "20")))
PREVIEW_CHARS = max(0, int(os.getenv("V3_PREVIEW_CHARS", "110")))

# 저장소 메타 문서. 유지보수 콘텐츠가 아니면서 도메인 어휘를 대량 포함해
# 렉시컬 상위를 점유한다. (진단 리포트 P0-α)
EXCLUDED_SOURCES = {
    "SIMPLIFY_CHANGELOG.md",
    "SIMPLIFY_VALIDATION_REPORT.md",
    "READABILITY_CLEANUP_REPORT.md",
    "READABILITY_FINAL_VALIDATION.md",
    "README.md",
}

# ---------------------------------------------------------------------------
# 도메인 사전
#   Phase 4 에서 graph_node_aliases 테이블 + 관리자 UI 로 이관 예정.
#   그때까지는 여기가 단일 출처이며, 수정 시 캐시가 자동 무효화되지 않으므로
#   /api/v3/graph?refresh=1 로 강제 재빌드해야 한다.
# ---------------------------------------------------------------------------

SYSTEM_TERMS: dict[str, list[str]] = {
    "홈페이지": ["홈페이지", "웹사이트", "웹 사이트", "website"],
    "그룹웨어": ["그룹웨어", "groupware"],
    "게시판": ["게시판", "bbs"],
    "회원관리": ["회원관리", "회원 관리", "멤버십", "회원가입"],
    "결제시스템": ["결제", "결재시스템", "이니시스", "kcp", "나이스페이", "payment"],
    "메일": ["메일", "이메일", "smtp", "메일서버"],
    "DB": ["데이터베이스", "database", "mysql", "mariadb", "oracle", "postgres", "mssql"],
    "WAS": ["톰캣", "tomcat", "jboss", "웹로직", "weblogic", "apache", "nginx", "was"],
    "SSL인증서": ["ssl", "인증서", "https", "tls"],
    "도메인": ["도메인", "domain", "dns", "네임서버"],
    "호스팅": ["호스팅", "hosting", "클라우드"],
    "백업": ["백업", "backup", "복구", "restore"],
    "모바일앱": ["안드로이드", "android", "ios", "모바일앱"],
    "관리자페이지": ["관리자", "admin", "어드민", "백오피스"],
    "검색": ["검색엔진", "elasticsearch"],
    "SMS": ["sms", "알림톡", "문자발송"],
    "보안": ["취약점", "해킹", "방화벽", "waf"],
    "학회관리": ["학회", "초록", "논문", "심사", "학술대회"],
    "예약": ["예약", "booking", "reservation"],
    "설문": ["설문", "survey"],
}

ISSUE_TERMS: dict[str, list[str]] = {
    "장애": ["장애", "다운", "먹통", "접속불가", "에러", "오류"],
    "성능": ["느림", "지연", "타임아웃", "timeout", "부하"],
    "갱신": ["갱신", "만료", "연장", "renewal"],
    "이관": ["이관", "이전", "마이그레이션", "migration"],
    "복구": ["복구", "롤백", "rollback", "재기동"],
    "기능개선": ["개선", "리뉴얼", "기능추가"],
}

CUSTOMER_ALIASES: dict[str, list[str]] = {
    "시도지사협의회": ["시도지사", "대한시도지사협회"],
    "KB손보CNS": ["kb손보", "kb손해보험", "손보cns"],
    "성의교정_카톨릭대학교": ["가톨릭대", "카톨릭대", "성의교정"],
    "유투바이오": ["u2bio"],
    "코웨이": ["coway"],
    "대한항공": ["korean air", "kal"],
}

NODE_TYPES = ("Customer", "Document", "Chunk", "System", "IssueType", "Ticket", "Person")

EDGE_TYPES = (
    "HAS_DOCUMENT", "BELONGS_TO", "HAS_CHUNK", "PART_OF",
    "MENTIONS", "MENTIONED_IN", "HAS_ISSUE", "OCCURS_IN",
    "REQUESTED_BY", "HAS_TICKET", "HANDLED", "HANDLED_BY",
)

# CSV 접수내역 임포트가 티켓 1건마다 마크다운 1개를 만들어 넣는 폴더.
# 폴더=고객사 규칙이 적용되면 가짜 고객사 하나에 티켓 수백 건이 문서로
# 매달려 그래프 전체를 압도한다. 문서 경로로는 제외하고, 대신
# maintenance_requests 테이블에서 Ticket/Person 노드로 적재한다.
TICKET_FOLDERS = {"유지보수_접수내역", "유지보수 접수내역"}

# 질의 의도별 허용 엣지. 무제한 확장은 노이즈를 폭증시킨다.
#
# 주의: 확장은 항상 '청크 또는 엔티티'에서 시작한다고 가정한다. 실제 검색에서
# 시드는 렉시컬/벡터 상위 청크와 링킹된 엔티티이지 고객사 노드가 아니다.
# 고객사/문서 노드가 시드로 들어오면 resolve_seeds() 가 청크로 내려준다.
INTENT_EDGES: dict[str, tuple[str, ...]] = {
    "customer_info": ("PART_OF", "HAS_CHUNK", "MENTIONS", "MENTIONED_IN"),
    "history": ("HAS_ISSUE", "OCCURS_IN", "MENTIONS", "MENTIONED_IN"),
    "manual": ("MENTIONS", "MENTIONED_IN", "PART_OF", "HAS_CHUNK"),
    "default": ("MENTIONS", "MENTIONED_IN", "PART_OF", "HAS_CHUNK", "HAS_ISSUE", "OCCURS_IN"),
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


# ---------------------------------------------------------------------------
# 자료구조
# ---------------------------------------------------------------------------

@dataclass
class Node:
    id: int
    type: str
    label: str
    customer: str | None = None
    degree: int = 0
    source: str | None = None
    preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "type": self.type, "label": self.label}
        if self.customer:
            out["customer"] = self.customer
        if self.degree:
            out["degree"] = self.degree
        if self.source:
            out["source"] = self.source
        if self.preview:
            out["preview"] = self.preview
        return out


@dataclass
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[tuple[int, int, str]] = field(default_factory=list)
    by_id: dict[int, Node] = field(default_factory=dict)
    adjacency: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    exp_weight: dict[int, float] = field(default_factory=dict)
    built_at: float = 0.0
    fingerprint: str = ""
    doc_count: int = 0
    ticket_count: int = 0
    ticket_docs_skipped: int = 0
    excluded: list[str] = field(default_factory=list)
    # 사전 후보 마이닝용 문서빈도. term -> 등장 문서 수
    term_doc_freq: dict[str, int] = field(default_factory=dict)
    term_customers: dict[str, set[str]] = field(default_factory=dict)
    term_doc_total: int = 0


# ---------------------------------------------------------------------------
# 청킹 — 진단 리포트 §2.4 의 하드코딩 섹션 스킵 리스트를 제거한 버전
# ---------------------------------------------------------------------------

def split_sections(text: str) -> list[tuple[list[str], str]]:
    sections: list[tuple[list[str], str]] = []
    stack: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(([p for p in stack if p], body))
        buf.clear()

    for line in (text or "").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            del stack[level - 1:]
            while len(stack) < level - 1:
                stack.append("")
            stack.append(match.group(2).strip())
        else:
            buf.append(line)
    flush()
    return sections


def chunk_document(text: str) -> list[tuple[list[str], str]]:
    out: list[tuple[list[str], str]] = []
    for path, body in split_sections(text):
        start = 0
        while start < len(body):
            part = body[start:start + CHUNK_MAX_CHARS]
            if len(part) >= CHUNK_MIN_CHARS:
                out.append((path, part))
            if start + CHUNK_MAX_CHARS >= len(body):
                break
            start += CHUNK_MAX_CHARS - CHUNK_OVERLAP
    return out


# ---------------------------------------------------------------------------
# 엔티티 추출
# ---------------------------------------------------------------------------

def extract_entities(text: str) -> tuple[list[str], list[str]]:
    low = (text or "").lower()
    systems = [name for name, variants in SYSTEM_TERMS.items()
               if any(v in low for v in variants)]
    issues = [name for name, variants in ISSUE_TERMS.items()
              if any(v in low for v in variants)]
    return systems, issues


def _is_excluded(source: str) -> bool:
    tail = (source or "").rsplit("/", 1)[-1]
    return tail in EXCLUDED_SOURCES


# ---------------------------------------------------------------------------
# 그래프 구축
# ---------------------------------------------------------------------------

def _norm_customer(name: str) -> str:
    return re.sub(r"[\s_]+", "", (name or "")).lower()


def build_graph(records: Sequence[Any], tickets: Sequence[dict] | None = None) -> Graph:
    graph = Graph()
    next_id = 1
    keys: dict[tuple[str, str], int] = {}

    def node(node_type: str, key: str, label: str, **kw) -> int:
        nonlocal next_id
        cache_key = (node_type, key)
        if cache_key in keys:
            return keys[cache_key]
        nid = next_id
        next_id += 1
        n = Node(id=nid, type=node_type, label=label, **kw)
        graph.nodes.append(n)
        graph.by_id[nid] = n
        graph.adjacency[nid] = []
        keys[cache_key] = nid
        return nid

    def edge(src: int, dst: int, edge_type: str) -> None:
        graph.edges.append((src, dst, edge_type))
        graph.adjacency[src].append((dst, edge_type))

    used = 0
    skipped_tickets = 0
    for record in records:
        source = getattr(record, "source", "") or ""
        if _is_excluded(source):
            graph.excluded.append(source)
            continue

        customer = (getattr(record, "customer", "") or "").strip() or "_공통"
        # 티켓 마크다운 사본은 문서 경로에서 제외 (아래에서 Ticket 노드로 적재)
        if customer in TICKET_FOLDERS or source.split("/", 1)[0] in TICKET_FOLDERS:
            skipped_tickets += 1
            continue

        if used >= GRAPH_MAX_DOCS:
            break
        used += 1
        title = (getattr(record, "title", "") or "").strip() or source
        content = getattr(record, "content", "") or ""

        cust_id = node("Customer", customer, customer, customer=customer)
        doc_id = node("Document", source, title, customer=customer, source=source)
        edge(cust_id, doc_id, "HAS_DOCUMENT")
        edge(doc_id, cust_id, "BELONGS_TO")

        # 사전 후보 마이닝: 문서 단위 유니크 용어 집계 (본문 전체 기준).
        # 고객사 집합도 함께 모은다 — 특정 고객사에 몰린 용어가 도메인 어휘일
        # 가능성이 높고, 전 고객사에 고루 퍼진 것은 템플릿 상용구다.
        graph.term_doc_total += 1
        for term in set(_TERM_RE.findall(content.lower())):
            if len(term) < 2 or term.isdigit() or term in _TERM_STOP:
                continue
            graph.term_doc_freq[term] = graph.term_doc_freq.get(term, 0) + 1
            graph.term_customers.setdefault(term, set()).add(customer)

        for ordinal, (heading_path, body) in enumerate(chunk_document(content)):
            chunk_key = f"{source}#{ordinal:04d}"
            label = heading_path[-1] if heading_path else f"{title} · {ordinal + 1}"
            chunk_id = node(
                "Chunk", chunk_key, label[:60], customer=customer, source=source,
                preview=re.sub(r"\s+", " ", body)[:PREVIEW_CHARS],
            )
            edge(doc_id, chunk_id, "HAS_CHUNK")
            edge(chunk_id, doc_id, "PART_OF")

            scope = body + " " + " ".join(heading_path) + " " + title
            systems, issues = extract_entities(scope)
            for name in systems:
                sid = node("System", name, name)
                edge(chunk_id, sid, "MENTIONS")
                edge(sid, chunk_id, "MENTIONED_IN")
            for name in issues:
                iid = node("IssueType", name, name)
                edge(chunk_id, iid, "HAS_ISSUE")
                edge(iid, chunk_id, "OCCURS_IN")

    graph.doc_count = used
    graph.ticket_docs_skipped = skipped_tickets

    # --- 티켓 / 담당자 (정규화 테이블에서) -------------------------------
    # 고객사 이름이 문서 폴더명과 정확히 일치하지 않을 수 있으므로 정규화 매칭.
    cust_by_norm = {
        _norm_customer(n.label): n.id
        for n in graph.nodes if n.type == "Customer"
    }
    ticket_count = 0
    for row in (tickets or []):
        cust_name = (row.get("customer") or "").strip()
        if not cust_name:
            continue
        cust_id = cust_by_norm.get(_norm_customer(cust_name))
        if cust_id is None:
            # 문서가 없는 고객사도 티켓으로는 존재할 수 있다
            cust_id = node("Customer", cust_name, cust_name, customer=cust_name)
            cust_by_norm[_norm_customer(cust_name)] = cust_id

        ticket_count += 1
        label = (row.get("title") or f"접수 {row.get('idx')}")[:60]
        tid = node("Ticket", f"ticket:{row.get('idx')}", label,
                   customer=cust_name, source=row.get("source"))
        edge(tid, cust_id, "REQUESTED_BY")
        edge(cust_id, tid, "HAS_TICKET")

        for key in ("manager_id", "worker_id"):
            pid_raw = row.get(key)
            if pid_raw in (None, "", 0):
                continue
            pid = node("Person", f"person:{pid_raw}", f"담당자 {pid_raw}")
            edge(pid, tid, "HANDLED")
            edge(tid, pid, "HANDLED_BY")

        # 티켓 제목에서도 시스템·이슈유형을 추출해 문서 쪽 엔티티와 연결
        systems, issues = extract_entities(label)
        for name in systems:
            sid = node("System", name, name)
            edge(tid, sid, "MENTIONS")
            edge(sid, tid, "MENTIONED_IN")
        for name in issues:
            iid = node("IssueType", name, name)
            edge(tid, iid, "HAS_ISSUE")
            edge(iid, tid, "OCCURS_IN")

    graph.ticket_count = ticket_count

    for nid, neighbours in graph.adjacency.items():
        graph.by_id[nid].degree = len(neighbours)

    _compute_hub_penalty(graph)
    graph.built_at = time.time()
    return graph


def _compute_hub_penalty(graph: Graph) -> None:
    """차수에 로그 역비례하는 확장 가중치.

    'SSL인증서'처럼 수백 청크에 연결된 허브를 경유한 확장은 정보량이 낮다.
    페널티가 없으면 2홉 확장이 코퍼스 대부분을 균일 점수로 끌어와
    렉시컬 결과를 희석시키기만 한다. (PoC 에서 실측 확인)
    """
    for nid, node in graph.by_id.items():
        degree = max(node.degree, 1)
        graph.exp_weight[nid] = 1.0 / (1.0 + 0.9 * math.log(degree)) if degree > 1 else 1.0


# ---------------------------------------------------------------------------
# 그래프 확장 (재귀 CTE 로 이식될 로직의 파이썬 구현)
# ---------------------------------------------------------------------------

def expand(
    graph: Graph,
    seeds: Sequence[int],
    *,
    edge_types: Sequence[str] | None = None,
    max_hop: int = 2,
    decay: float = 0.6,
    min_score: float = 0.05,
    use_hub_penalty: bool = True,
    limit: int = 400,
) -> dict[int, float]:
    allowed = set(edge_types) if edge_types else None
    best: dict[int, float] = {}
    frontier: list[tuple[int, float]] = [(s, 1.0) for s in seeds if s in graph.adjacency]

    for _ in range(max_hop):
        nxt: list[tuple[int, float]] = []
        for nid, score in frontier:
            for dst, edge_type in graph.adjacency.get(nid, ()):
                if allowed is not None and edge_type not in allowed:
                    continue
                penalty = graph.exp_weight.get(dst, 1.0) if use_hub_penalty else 1.0
                value = score * penalty * decay
                if value <= min_score:
                    continue
                if best.get(dst, 0.0) >= value:
                    continue
                best[dst] = value
                nxt.append((dst, value))
        if not nxt:
            break
        frontier = nxt

    for s in seeds:
        best.pop(s, None)
    if len(best) <= limit:
        return best
    top = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    return dict(top)


def resolve_seeds(graph: Graph, seeds: Sequence[int], *, per_doc: int = 0) -> list[int]:
    """Customer / Document 시드를 청크 시드로 치환한다.

    실제 검색에서 확장 시드는 렉시컬·벡터 상위 '청크'와 링킹된 '엔티티'다.
    고객사 노드에서 출발하면 2홉 안에 엔티티를 경유하지 못해 허브 문제가
    드러나지 않고, 그 결과 허브 페널티가 아무 일도 하지 않는 것처럼 보인다.
    UI 에서 고객사를 클릭하는 것은 '그 고객사 청크들을 시드로 삼는다'는 뜻이다.
    """
    out: list[int] = []
    for sid in seeds:
        node = graph.by_id.get(sid)
        if node is None:
            continue
        if node.type == "Chunk" or node.type in ("System", "IssueType"):
            out.append(sid)
            continue
        if node.type == "Customer":
            docs = [d for d, e in graph.adjacency.get(sid, ()) if e == "HAS_DOCUMENT"]
        else:
            docs = [sid]
        for doc in docs:
            chunks = [c for c, e in graph.adjacency.get(doc, ()) if e == "HAS_CHUNK"]
            out.extend(chunks[:per_doc] if per_doc > 0 else chunks)
    return list(dict.fromkeys(out))


def detect_intent(query: str) -> str:
    low = (query or "").lower()
    if any(w in low for w in ("이력", "사례", "과거", "비슷한", "유사", "이전에")):
        return "history"
    if any(w in low for w in ("어떻게", "방법", "절차", "설정", "매뉴얼")):
        return "manual"
    return "default"


def link_entities(graph: Graph, query: str) -> list[Node]:
    low = (query or "").lower()
    if not low.strip():
        return []
    found: dict[int, Node] = {}
    for node in graph.nodes:
        if node.type not in ("Customer", "System", "IssueType"):
            continue
        candidates = [node.label.lower()]
        if node.type == "Customer":
            candidates += [a.lower() for a in CUSTOMER_ALIASES.get(node.label, [])]
        elif node.type == "System":
            candidates += [v.lower() for v in SYSTEM_TERMS.get(node.label, [])]
        else:
            candidates += [v.lower() for v in ISSUE_TERMS.get(node.label, [])]
        if any(c and c in low for c in candidates):
            found[node.id] = node
    return list(found.values())


# ---------------------------------------------------------------------------
# 캐시
# ---------------------------------------------------------------------------

_cache: Graph | None = None
_cache_lock = threading.Lock()
_last_rebuild = 0.0

# 강제 재빌드 최소 간격. refresh=1 은 인증 없이 호출 가능하고 재빌드는
# Supabase 에서 전체 문서를 다시 읽으므로, 쿨다운이 없으면 DB/CPU 를 태우는
# 증폭 벡터가 된다. 쿨다운 내 요청은 조용히 캐시를 반환한다.
REBUILD_COOLDOWN = max(0, int(os.getenv("V3_REBUILD_COOLDOWN", "20")))


def _fingerprint(records: Sequence[Any]) -> str:
    """프로세스·재시작에 무관하게 안정적인 지문.

    Python 의 hash() 는 문자열에 대해 실행마다 시드가 달라져(PYTHONHASHSEED)
    같은 코퍼스인데도 재시작·워커마다 다른 값이 나온다. 지문이 UI 에 노출되고
    캐시 무효화 판단에 쓰이므로 sha1 을 쓴다.
    """
    digest = hashlib.sha1()
    count = 0
    for r in records:
        count += 1
        digest.update(f"{getattr(r, 'source', '')}\x1f{getattr(r, 'updated_at', '') or ''}\x1e".encode())
    return f"{count}:{digest.hexdigest()[:12]}"


def get_graph(loader, *, refresh: bool = False, ticket_loader=None) -> Graph:
    """loader() -> list[DocRecord]. 지문이 같고 TTL 내면 캐시를 재사용한다."""
    global _cache, _last_rebuild
    with _cache_lock:
        now = time.time()
        if refresh and _cache is not None and now - _last_rebuild < REBUILD_COOLDOWN:
            refresh = False
        if not refresh and _cache is not None and now - _cache.built_at < GRAPH_CACHE_TTL:
            return _cache
        records = loader()
        fingerprint = _fingerprint(records)
        if not refresh and _cache is not None and _cache.fingerprint == fingerprint:
            _cache.built_at = now
            return _cache
        tickets: list[dict] = []
        if ticket_loader is not None:
            try:
                tickets = ticket_loader() or []
            except Exception:
                tickets = []
        graph = build_graph(records, tickets)
        graph.fingerprint = fingerprint
        _cache = graph
        _last_rebuild = time.time()
        return graph


def invalidate() -> None:
    """문서 변경 시 호출. 다음 요청에서 그래프를 새로 만든다."""
    global _cache
    with _cache_lock:
        _cache = None


# ---------------------------------------------------------------------------
# 직렬화
# ---------------------------------------------------------------------------

def stats(graph: Graph) -> dict[str, Any]:
    node_counts: dict[str, int] = {}
    for node in graph.nodes:
        node_counts[node.type] = node_counts.get(node.type, 0) + 1
    edge_counts: dict[str, int] = {}
    for _, _, edge_type in graph.edges:
        edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1

    chunk_ids = {n.id for n in graph.nodes if n.type == "Chunk"}
    linked = set()
    for src, dst, edge_type in graph.edges:
        if edge_type in ("MENTIONS", "HAS_ISSUE") and src in chunk_ids:
            linked.add(src)

    hubs = sorted(
        (n for n in graph.nodes if n.type in ("System", "IssueType")),
        key=lambda n: -n.degree,
    )[:8]

    total_chunks = len(chunk_ids) or 1
    return {
        "docCount": graph.doc_count,
        "ticketCount": graph.ticket_count,
        "ticketDocsSkipped": graph.ticket_docs_skipped,
        "nodeCount": len(graph.nodes),
        "edgeCount": len(graph.edges),
        "nodeCounts": node_counts,
        "edgeCounts": edge_counts,
        "chunkCount": len(chunk_ids),
        "entityCoverage": round(len(linked) / total_chunks, 4),
        "excludedSources": graph.excluded,
        "hubs": [
            {"label": n.label, "type": n.type, "degree": n.degree,
             "share": round(n.degree / total_chunks, 4)}
            for n in hubs
        ],
        "builtAt": round(graph.built_at),
        "fingerprint": graph.fingerprint,
    }


def serialize(
    graph: Graph,
    *,
    customers: Sequence[str] | None = None,
    max_chunks_per_doc: int = 4,
    max_tickets_per_customer: int = 8,
    include_chunks: bool = True,
) -> dict[str, Any]:
    """시각화용 서브그래프.

    고객사 필터는 필수에 가깝다. 필터가 없으면 코퍼스 전량이 한 요청으로
    직렬화되므로, 인증이 도입되기 전까지는 SERIALIZE_MAX_NODES 로 잘라낸다.
    max_chunks_per_doc 은 0 이면 '청크 없음'이지 '무제한'이 아니다.
    """
    wanted = set(customers) if customers else None
    keep: set[int] = set()

    for node in graph.nodes:
        if node.type in ("System", "IssueType", "Person"):
            continue
        if wanted is not None and (node.customer or "") not in wanted:
            continue
        if node.type == "Chunk" and (not include_chunks or max_chunks_per_doc <= 0):
            continue
        # 티켓은 고객사당 수백 건까지 갈 수 있어 시각화에서는 상한을 둔다
        if node.type == "Ticket" and max_tickets_per_customer <= 0:
            continue
        keep.add(node.id)

    if max_tickets_per_customer > 0:
        cust_ticket_seen: dict[int, int] = {}
        allowed_tickets: set[int] = set()
        for src, dst, edge_type in graph.edges:
            if edge_type != "HAS_TICKET" or src not in keep or dst not in keep:
                continue
            seen = cust_ticket_seen.get(src, 0)
            if seen < max_tickets_per_customer:
                allowed_tickets.add(dst)
                cust_ticket_seen[src] = seen + 1
        keep = {n for n in keep if graph.by_id[n].type != "Ticket"} | allowed_tickets

    if include_chunks and max_chunks_per_doc > 0:
        doc_chunk_seen: dict[int, int] = {}
        allowed_chunks: set[int] = set()
        for src, dst, edge_type in graph.edges:
            if edge_type != "HAS_CHUNK" or src not in keep or dst not in keep:
                continue
            seen = doc_chunk_seen.get(src, 0)
            if seen < max_chunks_per_doc:
                allowed_chunks.add(dst)
                doc_chunk_seen[src] = seen + 1
        keep = {n for n in keep if graph.by_id[n].type != "Chunk"} | allowed_chunks

    truncated = False
    if len(keep) > SERIALIZE_MAX_NODES:
        truncated = True
        ordered = sorted(
            keep,
            key=lambda nid: (
                {"Customer": 0, "Document": 1, "Chunk": 2}.get(graph.by_id[nid].type, 3),
                nid,
            ),
        )
        keep = set(ordered[:SERIALIZE_MAX_NODES])

    for src, dst, edge_type in graph.edges:
        if edge_type in ("MENTIONS", "HAS_ISSUE", "HANDLED_BY") and src in keep:
            keep.add(dst)

    visible = ("HAS_DOCUMENT", "HAS_CHUNK", "MENTIONS", "HAS_ISSUE", "HAS_TICKET", "HANDLED_BY")
    nodes = [graph.by_id[n].to_dict() for n in keep]
    edges = [
        {"s": s, "t": t, "type": e}
        for s, t, e in graph.edges
        if s in keep and t in keep and e in visible
    ]
    return {"nodes": nodes, "edges": edges, "truncated": truncated}


_TERM_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9._-]{1,}")
_TERM_STOP = {
    "있습니다", "합니다", "입니다", "합니다만", "때문", "경우", "관련", "대한", "위한",
    "통해", "이후", "이전", "내용", "확인", "가능", "사용", "진행", "처리", "필요",
    "해당", "다음", "아래", "위의", "그리고", "하지만", "또한", "등을", "등의",
    "http", "https", "www", "com", "kr", "co", "html", "php", "index",
    "추가", "작업", "요약", "보고서", "작성", "수정", "방법", "고객사", "직접",
    "매뉴얼", "출처", "원문", "유의사항", "정보", "설명", "기준", "이용", "제공",
    "아니오", "네", "예시", "참고", "문서", "항목", "부분", "이것", "그것",
}

# 형태소 분석기가 없으므로 조사·어미가 붙은 표면형을 제거하기 위한 임시 규칙.
# 근본 해법은 kiwipiepy 도입이며 이건 그때까지의 땜질이다.
_KO_SUFFIX = (
    "에서", "에게", "으로", "로서", "로써", "이나", "거나", "지만", "면서",
    "습니다", "입니다", "합니다", "됩니다", "니다", "세요", "시오",
    "것입니다", "것이다", "하는", "되는", "관련된", "위해", "통한",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만",
)


def _is_encoding_fragment(term: str) -> bool:
    """퍼센트 인코딩된 한글 URL 의 파편.

    '%EB%A9%94...' 같은 URL 이 본문에 있으면 정규식이 eb, ec, ed, a9 같은
    2자리 16진수 조각을 용어로 잡는다. 한글 UTF-8 은 EA~ED 로 시작하므로
    특히 자주 나온다.
    """
    return bool(re.fullmatch(r"[0-9a-f]{2}", term))


def _looks_inflected(term: str) -> bool:
    """조사·어미가 붙은 표면형으로 보이면 True.

    '고객사와', '매뉴얼에서', '바꾸지' 같은 것을 걸러낸다.
    보수적으로: 접미사를 떼고 남은 어간이 2자 이상일 때만 굴절형으로 본다.
    """
    if not re.fullmatch(r"[가-힣]+", term):
        return False
    for suf in _KO_SUFFIX:
        if term.endswith(suf) and len(term) - len(suf) >= 2:
            return True
    return False


def mine_terms(graph: Graph, *, top: int = 80, min_docs: int = 3) -> list[dict[str, Any]]:
    """코퍼스에서 사전 후보 용어를 추출한다.

    사전이 소스코드에 하드코딩된 26개뿐이고 그마저 추측으로 만든 것이라,
    실제 코퍼스가 어떤 용어를 쓰는지 근거 없이 사전을 늘릴 수 없다.
    문서 빈도는 build_graph() 에서 본문 전체를 대상으로 집계해 둔다
    (미리보기 110자만 보면 표본이 너무 작다).
    여기서는 '문서 빈도가 충분히 높지만 너무 흔하지도 않은' 용어를 뽑는다.

    - df 가 너무 낮으면(min_docs 미만) 일회성 표현
    - df 비율이 너무 높으면(60% 초과) 변별력 없는 허브 후보
    - 이미 사전에 있는 용어는 제외

    반환값은 '자동 확정'이 아니라 사람이 검수할 후보 목록이다.
    """
    known: set[str] = set()
    for name, variants in list(SYSTEM_TERMS.items()) + list(ISSUE_TERMS.items()):
        known.add(name.lower())
        known.update(v.lower() for v in variants)

    n_docs = graph.term_doc_total or 1
    n_customers = len({n.label for n in graph.nodes if n.type == "Customer"}) or 1
    scored = []
    for term, df in graph.term_doc_freq.items():
        if term in known or df < min_docs:
            continue
        if _looks_inflected(term) or _is_encoding_fragment(term):
            continue
        if term.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        share = df / n_docs
        if share > 0.35:
            continue
        # 특정 고객사에 몰린 용어일수록 도메인 어휘일 가능성이 높다.
        # 전 고객사에 고루 퍼진 용어는 템플릿 상용구다.
        cust_share = len(graph.term_customers.get(term, ())) / n_customers
        concentration = 1.0 - min(cust_share, 1.0)
        scored.append({
            "term": term,
            "docFreq": df,
            "share": round(share, 4),
            "customers": len(graph.term_customers.get(term, ())),
            "score": round(df * (1.0 - share) * (0.3 + 0.7 * concentration), 2),
        })
    scored.sort(key=lambda t: -t["score"])
    return scored[:top]


def customer_list(graph: Graph) -> list[dict[str, Any]]:
    """고객사별 문서 수. 엣지를 한 번만 훑는다.

    이전 구현은 고객사마다 전체 엣지를 스캔해 O(고객사 x 엣지) 였고,
    /api/v3/stats 가 페이지 로드마다 호출되므로 코퍼스가 커지면 병목이 된다.
    """
    counts: dict[int, int] = {}
    for src, _dst, edge_type in graph.edges:
        if edge_type == "HAS_DOCUMENT":
            counts[src] = counts.get(src, 0) + 1
    out = [
        {"id": n.id, "name": n.label, "docCount": counts.get(n.id, 0)}
        for n in graph.nodes if n.type == "Customer"
    ]
    out.sort(key=lambda c: (-c["docCount"], c["name"]))
    return out
