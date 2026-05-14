from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "HK_유지보수팀_매뉴얼.md"
SIMPLE_DIR = ROOT / "organized_maintenance_docs_simple"
TODAY = "20260514"


ALIASES = {
    "(사)한국통신사업자연합회_KTOA": "벤처리움",
    "(주)케이비손보씨앤디서비스": "KB손보CNS",
    "KBCNS": "KB손보CNS",
    "KIAPS_차세대": "KIAPS_차세대",
    "KTOA_벤처리움": "벤처리움",
    "TOPEC": "TOPEC",
    "강동성심병원": "강동성심병원",
    "고대발전기금": "고대발전기금",
    "고신대학교복음병원": "고신대",
    "국립스포츠박물관": "국립스포츠박물관",
    "교보자산신탁": "교보자산신탁",
    "교보자산신탁 (생보부동산신탁)": "교보자산신탁",
    "김천의료원": "김천의료원",
    "대한고혈압학회": "고혈압학회",
    "대한시도지사협회": "시도지사협의회",
    "대한안과의사회": "안과의사회",
    "대한항공씨앤디서비스": "대한항공",
    "대한항공씨앤디서비스(주)": "대한항공",
    "더테이스터블": "한화",
    "더테이스터블 (한화푸드테크)": "한화",
    "더테이스터블(한화푸드테크)": "한화",
    "미래생활": "미래생활",
    "서울시 통합건강증진사업단": "서울통합건강증진사업",
    "서울통합건강증진사업지원단": "서울통합건강증진사업",
    "성의교정": "성의교정_카톨릭대학교",
    "성의교정 (카톨릭대)": "성의교정_카톨릭대학교",
    "성의교정 공동연구지원센터": "성의교정_공동연구지원센터",
    "성의교정_공동연구지원센터": "성의교정_공동연구지원센터",
    "성의교정_의생명건강과학과": "성의교정_의생명건강과학과",
    "성의교정_카톨릭대학교": "성의교정_카톨릭대학교",
    "수풍석뮤지엄": "수풍석뮤지엄",
    "순환자원유통지원센터": "한국순환자원",
    "숭실대글로벌미래교육원": "숭실대글로벌미래교육원",
    "시도지사협회": "시도지사협의회",
    "심부전학회": "심부전학회",
    "심초음파학회": "심초음파학회",
    "아셈": "아셈",
    "안동의료원": "안동의료원",
    "여성기업": "여성기업",
    "여성기업종합정보포털": "여성기업",
    "유엔거버넌스": "유엔거버넌스",
    "유통물가": "유통물가",
    "유통물가 이북": "유통물가",
    "이화의원": "이화의원",
    "인천감염병관리본부": "인천감염병관리지원단",
    "인천감염병관리지원단": "인천감염병관리지원단",
    "인하우스": "인하우스카운슬포럼",
    "장원의료재단": "장원의료재단",
    "장원의료재단 (유투바이오)": "장원의료재단",
    "장원의료재단_유투바이오": "장원의료재단",
    "지질동맥경화학회": "지질동맥경화학회",
    "차세대": "KIAPS_차세대",
    "차세대 (KIAPS)": "KIAPS_차세대",
    "코웨이": "코웨이",
    "틴매일경제": "틴매일경제",
    "트리니움병원": "트리니움",
    "파크랜드": "파크랜드",
    "하이덴탈코리아": "하이덴탈",
    "한국건설교통신기술협회": "한국건설교통신기술협회",
    "신기술협회": "한국건설교통신기술협회",
    "한국금융소비자보호재단": "한국금융소비자보호재단",
    "한국순환자원유통지원센터": "한국순환자원",
    "한국심초음파학회": "심초음파학회",
    "한국폐기물협회": "한국폐기물협회",
    "한국폐기물협회(교육)": "한국폐기물협회",
    "화성FC": "화성FC",
}


def clean_company(value: str) -> str:
    value = re.sub(r"^\*+|\*+$", "", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value


def canonical(value: str) -> str:
    value = clean_company(value)
    if value in ALIASES:
        return ALIASES[value]
    no_suffix = re.sub(r"\s+\([^)]*\)$", "", value)
    if no_suffix in ALIASES:
        return ALIASES[no_suffix]
    return value.replace(" ", "_")


def safe_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|#%&{}$!'@+`=]", "_", value)
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"_+", "_", value)
    return value.strip("._ ") or "미분류"


def section(text: str, heading: str, next_heading_pattern: str = r"\n## ") -> str:
    start = text.index(heading)
    rest = text[start:]
    match = re.search(next_heading_pattern, rest[len(heading):])
    if not match:
        return rest.strip()
    return rest[: len(heading) + match.start()].strip()


def add_chunk(chunks: dict[str, list[tuple[str, str, str]]], company: str, title: str, body: str, source: str) -> None:
    company = canonical(company)
    body = body.strip()
    if not body:
        return
    chunks[company].append((title.strip(), body, source))


def parse_markdown_table_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in block.splitlines():
        if not line.startswith("|"):
            continue
        if re.match(r"^\|[-: |]+\|$", line):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells and cells[0] not in {"고객사", "업체명"}:
            rows.append(cells)
    return rows


def parse_customer_work_table(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = section(text, "## 6. 고객사별 작업 정보")
    table_part = block.split("**모든 자리에서 작업 가능한 고객사**", 1)[0]
    headers = ["고객사", "접수 경로", "VPN", "원격", "이클립스", "실서버", "PC/MO", "주 업무", "비고"]
    for cells in parse_markdown_table_rows(table_part):
        if len(cells) < 9:
            continue
        company = cells[0]
        body = "\n".join(
            [
                "| 항목 | 내용 |",
                "|---|---|",
                *[f"| {headers[i]} | {cells[i] or '-'} |" for i in range(min(len(headers), len(cells)))],
            ]
        )
        add_chunk(chunks, company, "고객사별 작업 정보", body, "HK_유지보수팀_매뉴얼.md > 6. 고객사별 작업 정보")

    match = re.search(r"\*\*모든 자리에서 작업 가능한 고객사\*\*:\s*(.+)", block)
    if match:
        for company in [item.strip() for item in match.group(1).split(",")]:
            add_chunk(
                chunks,
                company,
                "공통 작업 가능 여부",
                "- 모든 자리에서 작업 가능한 고객사 목록에 포함되어 있습니다.",
                "HK_유지보수팀_매뉴얼.md > 6. 고객사별 작업 정보",
            )


def parse_customer_notice_sections(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = "\n\n".join(section(text, f"## {i}. 고객사 유의사항", r"\n## ").splitlines()[0:] for i in [])
    start = text.index("## 7. 고객사 유의사항")
    end = text.index("## 16. 포털 검색 관련")
    notices = text[start:end].strip()
    pattern = re.compile(r"^###\s+(.+?)\s*$", re.M)
    matches = list(pattern.finditer(notices))
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        body_start = match.start()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(notices)
        body = notices[body_start:body_end].strip()
        add_chunk(chunks, title, f"고객사 유의사항 - {title}", body, "HK_유지보수팀_매뉴얼.md > 고객사 유의사항")


def parse_report_sections(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = section(text, "## 4. 월간 보고서 작성")
    table_block = block.split("### 4-2. 업체별 보고서 작성 방법 및 나스 위치", 1)[0]
    headers = ["업체명", "담당자", "발송일", "고객사 메일 주소", "비고"]
    for cells in parse_markdown_table_rows(table_block):
        if len(cells) < 5:
            continue
        company = cells[0]
        body = "\n".join(
            [
                "| 항목 | 내용 |",
                "|---|---|",
                *[f"| {headers[i]} | {cells[i] or '-'} |" for i in range(min(len(headers), len(cells)))],
            ]
        )
        add_chunk(chunks, company, "보고서 발송 정보", body, "HK_유지보수팀_매뉴얼.md > 4-1. 보고서 발송 업체 목록")

    if "### 4-2. 업체별 보고서 작성 방법 및 나스 위치" not in block:
        return
    method_block = block.split("### 4-2. 업체별 보고서 작성 방법 및 나스 위치", 1)[1]
    matches = list(re.finditer(r"^\*\*(.+?)\*\*\s*$", method_block, re.M))
    for idx, match in enumerate(matches):
        company = clean_company(match.group(1))
        body_start = match.start()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(method_block)
        body = method_block[body_start:body_end].strip()
        add_chunk(chunks, company, f"보고서 작성 방법 - {company}", body, "HK_유지보수팀_매뉴얼.md > 4-2. 업체별 보고서 작성 방법")


def parse_ebook_webzine_sections(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = section(text, "## 5. 이북·웹진 작업")
    matches = list(re.finditer(r"^###\s+5-\d+\.\s+(.+?)\s*$", block, re.M))
    known = sorted(ALIASES.keys(), key=len, reverse=True)
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        body_start = match.start()
        body_end = matches[idx + 1].start() if idx + 1 < len(matches) else len(block)
        body = block[body_start:body_end].strip()
        targets = [name for name in known if name and name in title]
        if not targets and "TOPEC" in title:
            targets = ["TOPEC"]
        for target in targets[:1]:
            add_chunk(chunks, target, f"이북·웹진 작업 - {title}", body, "HK_유지보수팀_매뉴얼.md > 5. 이북·웹진 작업")


def parse_history_table(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = section(text, "## 18. 업체별 히스토리 및 참고사항")
    rows = parse_markdown_table_rows(block)
    for cells in rows:
        if len(cells) < 2:
            continue
        company = clean_company(cells[0].replace("**", ""))
        body = f"- 주요 히스토리 및 참고: {cells[1]}"
        add_chunk(chunks, company, "업체별 히스토리 및 참고사항", body, "HK_유지보수팀_매뉴얼.md > 18. 업체별 히스토리 및 참고사항")


def parse_analytics_customer_notes(text: str, chunks: dict[str, list[tuple[str, str, str]]]) -> None:
    block = section(text, "## 20. 구글 애널리틱스 외부연결 링크 관련")
    lines = []
    for line in block.splitlines():
        if "강동성심병원" in line:
            lines.append(line)
    if lines:
        add_chunk(
            chunks,
            "강동성심병원",
            "구글 애널리틱스 관련 참고",
            "\n".join(lines),
            "HK_유지보수팀_매뉴얼.md > 20. 구글 애널리틱스 외부연결 링크 관련",
        )


def existing_customer_docs(company_dir: Path) -> list[str]:
    return sorted(p.name for p in company_dir.glob("*.md") if not p.name.startswith("HK_공통매뉴얼_"))


def write_customer_files(chunks: dict[str, list[tuple[str, str, str]]]) -> list[tuple[str, int, str]]:
    results: list[tuple[str, int, str]] = []
    for company in sorted(chunks):
        company_dir = SIMPLE_DIR / safe_name(company)
        company_dir.mkdir(parents=True, exist_ok=True)
        file_path = company_dir / f"{safe_name(company)}_HK공통매뉴얼_추가정보_{TODAY}.md"
        related_docs = existing_customer_docs(company_dir)
        body: list[str] = [
            f"# {company} HK 공통매뉴얼 추가 정보",
            "",
            "## 1. 문서 개요",
            "",
            f"- 기업명: {company}",
            "- 문서 유형: HK 유지보수팀 매뉴얼에서 추출한 고객사별 추가 정보",
            "- 원본 파일명: `HK_유지보수팀_매뉴얼.md`",
            "- 원본 경로: `HK_유지보수팀_매뉴얼.md`",
            f"- 정리일: {TODAY}",
            "- 확인 필요 여부: 예",
            "",
            "## 2. 기존 정리본 문서",
            "",
        ]
        if related_docs:
            body.extend(f"- `{name}`" for name in related_docs)
        else:
            body.append("- 기존 간소화 정리본 문서 없음. HK 공통매뉴얼에서만 확인된 고객사/업체입니다.")
        body.extend(
            [
                "",
                "## 3. HK 매뉴얼에서 확인된 고객사별 정보",
                "",
                "아래 내용은 `HK_유지보수팀_매뉴얼.md`에서 해당 고객사와 직접 관련된 표 행, 유의사항, 보고서 작성 정보, 작업 방법, 히스토리를 추출한 것입니다. 원문 의미를 바꾸지 않고 보존했습니다.",
                "",
            ]
        )
        for index, (title, chunk, source) in enumerate(chunks[company], 1):
            body.extend(
                [
                    f"### 3-{index}. {title}",
                    "",
                    f"- 출처: `{source}`",
                    "",
                    chunk,
                    "",
                ]
            )
        body.extend(
            [
                "## 4. 확인 필요 사항",
                "",
                "- 고객사명 별칭 매핑으로 연결된 정보입니다. 실제 고객사 폴더와 명칭이 다를 수 있으므로 담당자 확인이 필요합니다.",
                "- HK 공통매뉴얼 원문 전체는 루트 `HK_유지보수팀_매뉴얼.md` 및 백업본에서 확인합니다.",
                "",
            ]
        )
        file_path.write_text("\n".join(body), encoding="utf-8", newline="\n")
        results.append((company, len(chunks[company]), file_path.relative_to(ROOT).as_posix()))
    return results


def cleanup_previous_generated_files() -> None:
    for path in SIMPLE_DIR.rglob(f"*_HK공통매뉴얼_추가정보_{TODAY}.md"):
        path.unlink()
    for name in ["HK_CUSTOMER_INFO_INDEX.md"]:
        path = SIMPLE_DIR / name
        if path.exists():
            path.unlink()
    # Remove only directories that became empty after deleting generated HK files.
    for directory in sorted([p for p in SIMPLE_DIR.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            next(directory.iterdir())
        except StopIteration:
            directory.rmdir()


def write_index(results: list[tuple[str, int, str]]) -> None:
    lines = [
        "# HK 공통매뉴얼 고객사별 반영 내역",
        "",
        "## 1. 개요",
        "",
        "`HK_유지보수팀_매뉴얼.md` 내부의 고객사별 작업 정보, 유의사항, 보고서 작성 정보, 이북·웹진 작업 정보, 업체별 히스토리를 고객사별 추가 문서로 분리했습니다.",
        "",
        "## 2. 반영 결과",
        "",
        "| 번호 | 고객사/분류 | 추출 항목 수 | 생성 문서 |",
        "|---:|---|---:|---|",
    ]
    for index, (company, count, path) in enumerate(results, 1):
        lines.append(f"| {index} | {company} | {count} | `{path}` |")
    lines.extend(
        [
            "",
            "## 3. 보존 원칙",
            "",
            "- 원본 `HK_유지보수팀_매뉴얼.md`는 수정하지 않았습니다.",
            "- 기존 `organized_maintenance_docs_simple` 문서는 삭제하지 않았습니다.",
            "- 고객사별 추가 문서는 별도 파일로 생성했습니다.",
            "- 고객사명 별칭 매핑이 필요한 경우 확인 필요로 표시했습니다.",
            "",
        ]
    )
    (SIMPLE_DIR / "HK_CUSTOMER_INFO_INDEX.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def update_simple_readme(results: list[tuple[str, int, str]]) -> None:
    readme = SIMPLE_DIR / "README.md"
    text = readme.read_text(encoding="utf-8")
    section = f"""

## 8. HK 공통매뉴얼 고객사별 추가 정보

루트 `HK_유지보수팀_매뉴얼.md`에 포함된 고객사별 작업 정보, 유의사항, 보고서 작성 정보, 이북·웹진 작업 정보, 업체별 히스토리를 고객사별 추가 문서로 분리했습니다.

- 생성 문서 수: {len(results)}
- 인덱스: `HK_CUSTOMER_INFO_INDEX.md`
- 파일명 형식: `고객사_HK공통매뉴얼_추가정보_{TODAY}.md`

각 추가 문서는 원본 매뉴얼의 해당 고객사 관련 내용을 별도 문서로 복사한 것이며, 원본 매뉴얼은 수정하지 않았습니다.
"""
    marker = "\n## 8. HK 공통매뉴얼 고객사별 추가 정보\n"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip() + section
    else:
        text = text.rstrip() + section
    readme.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    cleanup_previous_generated_files()
    chunks: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    parse_report_sections(text, chunks)
    parse_ebook_webzine_sections(text, chunks)
    parse_customer_work_table(text, chunks)
    parse_customer_notice_sections(text, chunks)
    parse_history_table(text, chunks)
    parse_analytics_customer_notes(text, chunks)

    results = write_customer_files(chunks)
    write_index(results)
    update_simple_readme(results)

    print(f"customers={len(results)}")
    print(f"chunks={sum(count for _, count, _ in results)}")
    print("index=organized_maintenance_docs_simple/HK_CUSTOMER_INFO_INDEX.md")


if __name__ == "__main__":
    main()
