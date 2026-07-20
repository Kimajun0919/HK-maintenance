#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""도메인 용어 사전 후보 마이닝 (오프라인 전용).

왜 오프라인인가
--------------
kiwipiepy 는 형태소 분석 품질이 좋지만 **약 500MB 의 힙 메모리**를 씁니다
(실측: RssAnon 509MB, 모델 디스크 104MB). Render 512Mi 플랜에서는 런타임에
올릴 수 없습니다. mmap 이 아니라 순수 힙이라 회수도 되지 않습니다.

그래서 형태소 분석은 **이 스크립트에서 1회 실행**하고, 결과를
`backend/domain_terms.json` 으로 떨어뜨립니다. 런타임(graph_v3)은 그 JSON 만
읽으므로 Kiwi 의존성도 메모리 비용도 0 입니다.

온프레미스 전환(Phase 2) 후에는 메모리 제약이 사라지므로 Kiwi 를 런타임에
올려 FTS 표제어 추출과 질의 정규화에 쓰는 것이 맞습니다. 그때가 Kiwi 의
진짜 효용 구간입니다 — 사전 후보 마이닝만 놓고 보면 개선폭은 크지 않습니다
(고유 용어 33% 감소, 상위 후보는 정규식 방식과 대부분 동일).

사용법
------
    pip install kiwipiepy
    python scripts/mine_terms.py --docs <코퍼스경로> -o backend/domain_terms.json
    python scripts/mine_terms.py --supabase -o backend/domain_terms.json

Kiwi 가 없으면 정규식 폴백으로 동작하며, 그 사실을 출력에 남깁니다.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

NOUN_TAGS = ("NNG", "NNP", "SL", "SH")

STOPWORDS = {
    "있습니다", "합니다", "입니다", "때문", "경우", "관련", "대한", "위한", "통해",
    "이후", "이전", "내용", "확인", "가능", "사용", "진행", "처리", "필요", "해당",
    "다음", "아래", "위의", "그리고", "하지만", "또한", "추가", "작업", "요약",
    "보고서", "작성", "수정", "방법", "고객사", "직접", "매뉴얼", "출처", "원문",
    "유의사항", "정보", "설명", "기준", "이용", "제공", "아니오", "예시", "참고",
    "문서", "항목", "부분", "등록", "변경", "요청", "업무", "공통",
    "http", "https", "www", "com", "kr", "co", "html", "php", "index", "png", "jpg",
}

_FALLBACK_RE = re.compile(r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9._-]{1,}")
_KO_SUFFIX = (
    "에서", "에게", "으로", "로서", "로써", "이나", "거나", "지만", "면서",
    "습니다", "입니다", "합니다", "됩니다", "니다", "세요", "시오",
    "것입니다", "것이다", "하는", "되는", "관련된", "위해", "통한",
    "은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만",
)


def _looks_inflected(term: str) -> bool:
    if not re.fullmatch(r"[가-힣]+", term):
        return False
    return any(term.endswith(s) and len(term) - len(s) >= 2 for s in _KO_SUFFIX)


def _is_noise(term: str) -> bool:
    if len(term) < 2 or term in STOPWORDS:
        return True
    if term[0].isdigit() or term.replace(".", "").isdigit():
        return True
    if re.fullmatch(r"[0-9a-f]{2}", term):          # 퍼센트 인코딩 파편
        return True
    if term.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return True
    return False


class Extractor:
    """Kiwi 가 있으면 형태소 기반, 없으면 정규식 폴백."""

    def __init__(self) -> None:
        self.kiwi = None
        try:
            from kiwipiepy import Kiwi
            self.kiwi = Kiwi()
        except Exception:
            pass
        self.mode = "kiwi" if self.kiwi else "regex"

    def terms(self, text: str) -> set[str]:
        if self.kiwi is None:
            return self._regex(text)
        return self._kiwi(text)

    def _regex(self, text: str) -> set[str]:
        out = set()
        for raw in _FALLBACK_RE.findall(text.lower()):
            if _is_noise(raw) or _looks_inflected(raw):
                continue
            out.add(raw)
        return out

    def _kiwi(self, text: str) -> set[str]:
        """명사 토큰 추출 + 인접 명사 복합어 복원.

        Kiwi 는 '서버도메인'을 '서버'+'도메인'으로, '관리자계정'을
        '관리자'+'계정'으로 쪼갠다. 유지보수 도메인에서는 복합어 쪽이
        훨씬 유용하므로, 원문에서 공백 없이 붙어 있던 명사는 다시 잇는다.
        단일 형태소도 함께 남겨 두 형태 모두 후보가 되게 한다.
        """
        out: set[str] = set()
        for sent in self.kiwi.tokenize(text, split_sents=True):
            run: list[str] = []
            prev_end = None
            for tok in sent:
                if tok.tag in NOUN_TAGS and len(tok.form) > 1:
                    if prev_end is not None and tok.start != prev_end:
                        if run:
                            out.add("".join(run))
                        run = []
                    run.append(tok.form)
                    out.add(tok.form)
                    prev_end = tok.start + len(tok.form)
                else:
                    if run:
                        out.add("".join(run))
                    run = []
                    prev_end = None
            if run:
                out.add("".join(run))
        return {t.lower() for t in out if not _is_noise(t.lower())}


def load_docs_from_files(root: Path) -> list[tuple[str, str]]:
    import graph_v3
    docs = []
    for path in sorted(root.rglob("*.md")):
        if path.name in graph_v3.EXCLUDED_SOURCES:
            continue
        rel = path.relative_to(root)
        customer = rel.parts[0] if len(rel.parts) > 1 else "_공통"
        if customer in graph_v3.TICKET_FOLDERS:
            continue
        docs.append((customer, path.read_text(encoding="utf-8", errors="replace")))
    return docs


def load_docs_from_db() -> list[tuple[str, str]]:
    import graph_v3
    from storage import _doc_records
    docs = []
    for rec in _doc_records():
        source = getattr(rec, "source", "") or ""
        customer = (getattr(rec, "customer", "") or "").strip() or "_공통"
        if source.rsplit("/", 1)[-1] in graph_v3.EXCLUDED_SOURCES:
            continue
        if customer in graph_v3.TICKET_FOLDERS:
            continue
        docs.append((customer, getattr(rec, "content", "") or ""))
    return docs


def mine(docs, extractor, *, min_docs=3, max_share=0.35, top=150):
    df = collections.Counter()
    customers = collections.defaultdict(set)
    for customer, text in docs:
        for term in extractor.terms(text):
            df[term] += 1
            customers[term].add(customer)

    n_docs = len(docs) or 1
    n_cust = len({c for c, _ in docs}) or 1
    scored = []
    for term, freq in df.items():
        if freq < min_docs:
            continue
        share = freq / n_docs
        if share > max_share:
            continue
        # 특정 고객사에 몰린 용어일수록 도메인 어휘일 가능성이 높다
        concentration = 1.0 - min(len(customers[term]) / n_cust, 1.0)
        scored.append({
            "term": term,
            "docFreq": freq,
            "customers": len(customers[term]),
            "share": round(share, 4),
            "score": round(freq * (1 - share) * (0.3 + 0.7 * concentration), 2),
        })
    scored.sort(key=lambda t: -t["score"])
    return scored[:top], len(df), n_docs, n_cust


def main() -> None:
    ap = argparse.ArgumentParser(description="도메인 용어 사전 후보 마이닝")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--docs", help="마크다운 코퍼스 디렉터리")
    src.add_argument("--supabase", action="store_true", help="운영 DB에서 읽기")
    ap.add_argument("-o", "--out", default=str(ROOT / "backend" / "domain_terms.json"))
    ap.add_argument("--top", type=int, default=150)
    ap.add_argument("--min-docs", type=int, default=3)
    args = ap.parse_args()

    docs = load_docs_from_db() if args.supabase else load_docs_from_files(Path(args.docs))
    if not docs:
        print("문서를 찾지 못했습니다.", file=sys.stderr)
        raise SystemExit(1)

    ex = Extractor()
    if ex.mode == "regex":
        print("! kiwipiepy 가 없어 정규식 폴백으로 동작합니다 "
              "(pip install kiwipiepy 권장)", file=sys.stderr)

    candidates, unique_terms, n_docs, n_cust = mine(
        docs, ex, min_docs=args.min_docs, top=args.top)

    payload = {
        "_comment": "scripts/mine_terms.py 산출물. 자동 확정본이 아니라 검수용 후보 목록입니다.",
        "mode": ex.mode,
        "corpusDocs": n_docs,
        "corpusCustomers": n_cust,
        "uniqueTerms": unique_terms,
        "candidates": candidates,
        "approved": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"모드 {ex.mode} | 문서 {n_docs} | 고객사 {n_cust} | 고유용어 {unique_terms}")
    print(f"후보 {len(candidates)}개 → {out}\n")
    print(f"{'용어':<22}{'df':>5}{'고객사':>7}")
    print("-" * 36)
    for c in candidates[:30]:
        print(f"{c['term']:<22}{c['docFreq']:>5}{c['customers']:>7}")
    print("\n검수 후 쓸 용어를 approved 배열로 옮기면 런타임이 사전에 반영합니다.")


if __name__ == "__main__":
    main()
