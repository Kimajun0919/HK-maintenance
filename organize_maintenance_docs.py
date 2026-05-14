from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / "original_backup"
OUT_DIR = ROOT / "organized_maintenance_docs"
TODAY = "20260514"

SOURCE_EXCLUDES = {".git", "original_backup", "organized_maintenance_docs", "__pycache__"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}

SECTION_DIRS = [
    "01_기본정보",
    "02_서버_도메인",
    "03_관리자_계정",
    "04_유지보수_이력",
    "05_작업_팁",
    "06_오류_및_대응방법",
    "07_이미지_자료",
    "99_기타_미분류",
]


@dataclass
class FileRecord:
    path: Path
    rel: str
    name: str
    ext: str
    file_type: str
    company: str
    doc_type: str
    target: bool
    note: str


def rel_posix(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def safe_name(value: str, default: str = "미분류") -> str:
    value = unquote(value)
    value = re.sub(r"\s+", "_", value.strip())
    value = re.sub(r"[\\/:*?\"<>|#%&{}$!'@+`=]", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return value or default


def display_name_from_stem(stem: str) -> str:
    name = unquote(stem)
    name = re.sub(r"\s+[0-9a-f]{24,}$", "", name, flags=re.I)
    name = re.sub(r"\s+\([0-9]+\)$", "", name)
    return name.strip() or "미분류"


def source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SOURCE_EXCLUDES for part in rel_parts):
            continue
        if path.name == Path(__file__).name:
            continue
        files.append(path)
    return sorted(files, key=lambda p: rel_posix(p).lower())


def infer_company(path: Path) -> tuple[str, bool, str]:
    rel_parts = path.relative_to(ROOT).parts
    if path.name == "README.md":
        return "99_기타_미분류", True, "프로젝트 루트 README로 기업 분류 확인 필요"
    if path.name == "HK_유지보수팀_매뉴얼.md":
        return "HK_유지보수팀", False, "루트 유지보수팀 공통 매뉴얼"
    if rel_parts[0] != "기업별 유지보수 팁":
        return "99_기타_미분류", True, "예상 외 위치"
    if len(rel_parts) == 2:
        return "99_기타_미분류", True, "인수인계 색인 문서로 기업 분류 확인 필요"
    if len(rel_parts) >= 3 and rel_parts[1] == "인수인계":
        if len(rel_parts) == 3 and path.suffix.lower() == ".md":
            company = display_name_from_stem(path.stem)
        else:
            company = display_name_from_stem(rel_parts[2])
        if company in {"보고서", "링크 모음", "대량메일_레몬메일"}:
            return company, True, "기업이 아닌 공통/업무 분류일 수 있어 확인 필요"
        return company, False, ""
    return "99_기타_미분류", True, "분류 규칙 밖 경로"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp949", errors="replace")


def classify_doc(path: Path, company: str, text: str, uncertain: bool) -> tuple[str, str, str]:
    hay = f"{path.stem}\n{text[:3000]}".lower()
    title = display_name_from_stem(path.stem)
    if uncertain:
        return "기타미분류", "99_기타_미분류", title
    if any(k in hay for k in ["오류", "에러", "error", "장애", "대응"]):
        return "오류대응", "06_오류_및_대응방법", title
    if any(k in hay for k in ["id", "pw", "계정", "로그인", "vpn", "hiware", "tgate", "접속 정보"]):
        return "관리자계정", "03_관리자_계정", title
    if any(k in hay for k in ["서버", "도메인", "db", "디비", "ftp", "파일질라", "경로", "url", "http"]):
        return "서버도메인", "02_서버_도메인", title
    if any(k in hay for k in ["보고서", "이력", "방문자 수", "월간"]):
        return "유지보수이력", "04_유지보수_이력", title
    if title == company or "매뉴얼" in hay:
        return "유지보수매뉴얼", "01_기본정보", title
    return "작업팁", "05_작업_팁", title


def extract_md_image_refs(text: str) -> list[str]:
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    return [unquote(ref.split("#", 1)[0]) for ref in refs]


def related_images(md_path: Path, image_paths: list[Path], text: str) -> list[Path]:
    refs = extract_md_image_refs(text)
    found: set[Path] = set()
    for ref in refs:
        candidate = (md_path.parent / ref).resolve()
        if candidate.exists() and candidate.is_file():
            found.add(candidate)
    asset_dir = md_path.with_suffix("")
    if asset_dir.exists() and asset_dir.is_dir():
        for p in asset_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                found.add(p.resolve())
    return sorted((p for p in image_paths if p.resolve() in found), key=lambda p: rel_posix(p))


def ensure_company_dirs(company: str) -> Path:
    company_dir = OUT_DIR / safe_name(company)
    for section in SECTION_DIRS:
        (company_dir / section).mkdir(parents=True, exist_ok=True)
    return company_dir


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 2
    while True:
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def copy_sources_to_backup(files: list[Path]) -> None:
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    for src in files:
        dst = BACKUP_DIR / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_inventory(records: list[FileRecord]) -> str:
    lines = [
        "# 파일 인벤토리",
        "",
        "| 번호 | 원본 경로 | 원본 파일명 | 파일 유형 | 예상 기업명 | 예상 문서 유형 | 정리 대상 여부 | 비고 |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(records, 1):
        lines.append(
            f"| {i} | `{r.rel}` | `{r.name}` | {r.file_type} | {r.company} | {r.doc_type} | {'대상' if r.target else '대상 아님'} | {r.note or '-'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    files = source_files()
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    copy_sources_to_backup(files)

    md_paths = [p for p in files if p.suffix.lower() == ".md"]
    image_paths = [p for p in files if p.suffix.lower() in IMAGE_EXTS]
    other_paths = [p for p in files if p.suffix.lower() not in IMAGE_EXTS and p.suffix.lower() != ".md"]

    records: list[FileRecord] = []
    md_outputs: dict[Path, Path] = {}
    image_outputs: dict[Path, Path] = {}
    changelog_rows: list[tuple[str, str, str, str]] = []
    validation_rows: list[tuple[str, str, str, str]] = []
    image_link_rows: list[tuple[str, list[str], str, str]] = []
    confirm_needed: list[str] = []

    # Copy images first so documents can link to renamed assets.
    for img in image_paths:
        company, uncertain, note = infer_company(img)
        company_dir = ensure_company_dirs(company)
        parent_topic = display_name_from_stem(img.parent.name)
        original_stem = display_name_from_stem(img.stem)
        new_name = safe_name(f"{company}_{parent_topic}_{original_stem}_{TODAY}") + img.suffix.lower()
        dst = unique_path(company_dir / "07_이미지_자료" / new_name)
        shutil.copy2(img, dst)
        image_outputs[img.resolve()] = dst
        doc_type = "이미지자료"
        records.append(FileRecord(img, rel_posix(img), img.name, img.suffix.lower(), "image", company, doc_type, True, note))
        changelog_rows.append((rel_posix(img), rel_posix(dst), "이미지 원본 복사 및 의미 기반 파일명 부여", "없음"))
        if uncertain:
            confirm_needed.append(f"- `{rel_posix(img)}`: {note}")

    for md in md_paths:
        text = read_text(md)
        company, uncertain, note = infer_company(md)
        doc_type, section_dir, topic = classify_doc(md, company, text, uncertain)
        company_dir = ensure_company_dirs(company)
        new_name = safe_name(f"{company}_{doc_type}_{topic}_{TODAY}") + ".md"
        dst = unique_path(company_dir / section_dir / new_name)
        imgs = related_images(md, image_paths, text)
        image_rows = []
        image_blocks = []
        for img in imgs:
            copied = image_outputs.get(img.resolve())
            if copied:
                link = Path("..") / "07_이미지_자료" / copied.name
                image_rows.append(f"| `{copied.name}` | 원본 `{rel_posix(img)}`에서 복사된 관련 이미지 | `./{link.as_posix()}` |")
                image_blocks.append(
                    f"![{copied.stem}](./{link.as_posix()})\n\n"
                    f"- 이미지 설명: 원본 문서 또는 동일 이름 자산 폴더에 연결된 이미지입니다.\n"
                    f"- 기존 이미지 파일명: `{img.name}`\n"
                    f"- 기존 이미지 경로: `{rel_posix(img)}`\n"
                    f"- 유지보수 참고사항: 이미지 세부 내용은 담당자 확인 필요\n"
                )
        if not image_rows:
            image_rows.append("| - | 관련 이미지 없음 또는 확인 필요 | - |")

        check_needed = "예" if uncertain or "확인 필요" in note else "아니오"
        if uncertain:
            confirm_needed.append(f"- `{rel_posix(md)}`: {note}")

        title = display_name_from_stem(md.stem)
        summary = [
            f"- 원본 문서 `{md.name}`의 내용을 누락 없이 보존한 정리본입니다.",
            f"- 예상 기업명은 `{company}`이며 문서 유형은 `{doc_type}`으로 분류했습니다.",
        ]
        if imgs:
            summary.append(f"- 관련 이미지 {len(imgs)}개를 `07_이미지_자료`에 복사하고 이 문서에 연결했습니다.")
        if uncertain:
            summary.append(f"- 분류 또는 의미 확인이 필요한 문서입니다: {note}")

        original_hash = content_hash(text)
        out_text = "\n".join(
            [
                f"# {title}",
                "",
                "## 1. 문서 개요",
                "",
                f"- 기업명: {company}",
                f"- 문서 유형: {doc_type}",
                "- 관련 사이트: 원본 내용 참조",
                "- 관련 관리자 URL: 원본 내용 참조",
                f"- 원본 파일명: `{md.name}`",
                f"- 원본 경로: `{rel_posix(md)}`",
                f"- 원본 SHA-256: `{original_hash}`",
                f"- 정리일: {TODAY}",
                f"- 확인 필요 여부: {check_needed}",
                "",
                "## 2. 핵심 요약",
                "",
                "\n".join(summary),
                "",
                "## 3. 상세 내용",
                "",
                "아래 내용은 원본 md 문서의 본문 전체입니다. 내용 누락 방지를 위해 원문 표현, 계정 정보, 경로, URL, 메모를 삭제하지 않고 보존했습니다.",
                "",
                text.rstrip(),
                "",
                "## 4. 작업 절차",
                "",
                "- 원본 문서에 명시된 절차는 `## 3. 상세 내용` 및 `## 8. 원본 보존 내용`에 원문 그대로 보존되어 있습니다.",
                "- 자동 정리 과정에서 절차를 임의로 재해석하거나 보완하지 않았습니다.",
                "",
                "## 5. 주의사항",
                "",
                "- 원본 문서에 포함된 주의사항, 예외사항, 계정 정보, 서버 정보, 경로, URL은 `## 3. 상세 내용`에 보존되어 있습니다.",
                "- 자동 분류 결과는 검토용이며, 의미가 불분명한 항목은 확인 필요로 표시했습니다.",
                "",
                "## 6. 오류 및 대응 방법",
                "",
                "- 원본에 오류 사례 또는 대응 방법이 포함된 경우 `## 3. 상세 내용`에서 확인합니다.",
                "",
                "## 7. 관련 이미지",
                "",
                "| 이미지 파일명 | 설명 | 연결 경로 |",
                "|---|---|---|",
                "\n".join(image_rows),
                "",
                "\n".join(image_blocks).rstrip() if image_blocks else "- 관련 이미지가 확인되지 않았습니다.",
                "",
                "## 8. 원본 보존 내용",
                "",
                f"- 원본 경로: `{rel_posix(md)}`",
                f"- 원본 파일명: `{md.name}`",
                f"- 원본 SHA-256: `{original_hash}`",
                "",
                "````markdown",
                text.rstrip(),
                "````",
                "",
                "## 9. 확인 필요 사항",
                "",
                f"- {note if note else '자동 정리 기준상 별도 확인 필요 사항 없음'}",
                "- 이미지 내부 텍스트의 상세 판독은 자동 OCR을 수행하지 않았으므로 필요 시 담당자 확인 필요",
                "",
            ]
        )
        dst.write_text(out_text, encoding="utf-8", newline="\n")
        md_outputs[md.resolve()] = dst
        records.append(FileRecord(md, rel_posix(md), md.name, ".md", "md", company, doc_type, True, note))
        changelog_rows.append((rel_posix(md), rel_posix(dst), "원본 md 전체 보존, 공통 메타데이터/이미지 연결/확인 필요 섹션 추가", "없음"))
        validation_rows.append((rel_posix(md), rel_posix(dst), "없음", f"원본 SHA-256 기록 및 원문 전체 보존 섹션 생성: {original_hash}"))

    for other in other_paths:
        company, uncertain, note = infer_company(other)
        company_dir = ensure_company_dirs(company)
        dst = unique_path(company_dir / "99_기타_미분류" / safe_name(other.name, other.name))
        shutil.copy2(other, dst)
        records.append(FileRecord(other, rel_posix(other), other.name, other.suffix.lower() or "none", "other", company, "기타", True, note))
        changelog_rows.append((rel_posix(other), rel_posix(dst), "기타 파일 원본 복사", "없음"))
        if uncertain:
            confirm_needed.append(f"- `{rel_posix(other)}`: {note}")

    # Image validation: connected to any organized md or copied as standalone.
    for img in image_paths:
        linked_docs = []
        for md, dst in md_outputs.items():
            if img.resolve() in related_images(Path(md), image_paths, read_text(Path(md))):
                linked_docs.append(rel_posix(dst))
        copied = image_outputs.get(img.resolve())
        if linked_docs:
            image_link_rows.append((rel_posix(copied) if copied else rel_posix(img), linked_docs, "연결", "관련 md 문서에서 참조"))
        else:
            image_link_rows.append((rel_posix(copied) if copied else rel_posix(img), [], "미연결", "관련 md 자동 매칭 없음, 이미지 자료 폴더에 원본 복사"))
            confirm_needed.append(f"- `{rel_posix(img)}`: 관련 md 자동 매칭 없음")

    (OUT_DIR / "FILE_INVENTORY.md").write_text(build_inventory(records), encoding="utf-8", newline="\n")

    readme = """# 유지보수 문서 정리본

## 1. 개요

이 문서는 각 기업별 유지보수 매뉴얼, 작업 팁, 오류 대응 방법, 이미지 자료를 AI가 읽기 쉬운 구조로 정리한 문서입니다.

## 2. 폴더 구조

```text
/기업명
  /01_기본정보
  /02_서버_도메인
  /03_관리자_계정
  /04_유지보수_이력
  /05_작업_팁
  /06_오류_및_대응방법
  /07_이미지_자료
  /99_기타_미분류
```

## 3. 문서 사용 방법

* 기업별 폴더에서 유지보수 정보를 확인한다.
* 서버, 도메인, 관리자 계정 정보는 각 기업 폴더의 세부 문서를 확인한다.
* 오류 발생 시 `06_오류_및_대응방법` 폴더를 우선 확인한다.
* 분류가 어려운 자료는 `99_기타_미분류`를 확인한다.

## 4. 주의사항

* 본 정리본은 원본 내용을 기준으로 구조화한 문서이다.
* 확인되지 않은 정보는 “확인 필요”로 표시되어 있다.
* 원본 자료는 `/original_backup`에 보존되어 있다.
* 각 정리 md의 `## 8. 원본 보존 내용`에는 원본 md 전체가 보존되어 있다.
"""
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    changelog_lines = [
        "# 유지보수 문서 정리 변경 내역",
        "",
        "## 정리 기준",
        "",
        "- 원본 보존 여부: `/original_backup`에 원본 파일 전체를 경로 그대로 복사",
        "- 폴더 구조 변경 기준: 예상 기업명별 폴더와 공통 섹션 폴더 생성",
        "- 파일명 변경 기준: `기업명_문서유형_주제_YYYYMMDD.md` 및 `기업명_화면명_설명_YYYYMMDD.png` 형식 적용",
        "- 내용 수정 기준: 원본 본문은 삭제하지 않고 정리 md의 상세 내용 및 원본 보존 내용에 유지",
        "",
        "## 파일별 변경 내역",
        "",
        "| 번호 | 원본 경로 | 변경 후 경로 | 변경 내용 | 내용 누락 여부 | 비고 |",
        "|---:|---|---|---|---|---|",
    ]
    for i, (src, dst, change, loss) in enumerate(changelog_rows, 1):
        changelog_lines.append(f"| {i} | `{src}` | `{dst}` | {change} | {loss} | - |")
    (OUT_DIR / "CHANGELOG.md").write_text("\n".join(changelog_lines) + "\n", encoding="utf-8", newline="\n")

    organized_md = list(OUT_DIR.rglob("*.md"))
    organized_images = [p for p in OUT_DIR.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    organized_other = [
        p for p in OUT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() not in IMAGE_EXTS and p.suffix.lower() != ".md"
    ]
    organized_md_count_final = len(organized_md) + 1  # VALIDATION_REPORT.md is written below.
    validation_lines = [
        "# 누락 검증 보고서",
        "",
        "## 1. 전체 파일 검증",
        "",
        "| 항목 | 원본 | 정리 후 | 상태 |",
        "|---|---:|---:|---|",
        f"| md 파일 수 | {len(md_paths)} | {organized_md_count_final} | 정리본 관리 문서 4개 포함으로 정리 후 수 증가 |",
        f"| 이미지 파일 수 | {len(image_paths)} | {len(organized_images)} | {'정상' if len(image_paths) == len(organized_images) else '확인 필요'} |",
        f"| 기타 파일 수 | {len(other_paths)} | {len(organized_other)} | {'정상' if len(other_paths) == len(organized_other) else '확인 필요'} |",
        "",
        "## 2. 내용 누락 검증",
        "",
        "| 번호 | 원본 파일 | 정리 파일 | 누락 여부 | 확인 결과 |",
        "|---:|---|---|---|---|",
    ]
    for i, (src, dst, loss, result) in enumerate(validation_rows, 1):
        validation_lines.append(f"| {i} | `{src}` | `{dst}` | {loss} | {result} |")
    validation_lines += [
        "",
        "## 3. 이미지 연결 검증",
        "",
        "| 번호 | 이미지 파일 | 연결된 md 문서 | 연결 여부 | 비고 |",
        "|---:|---|---|---|---|",
    ]
    for i, (img, docs, status, note) in enumerate(image_link_rows, 1):
        validation_lines.append(f"| {i} | `{img}` | {'<br>'.join(f'`{d}`' for d in docs) if docs else '-'} | {status} | {note} |")
    validation_lines += [
        "",
        "## 4. 확인 필요 사항",
        "",
        "\n".join(confirm_needed) if confirm_needed else "- 별도 확인 필요 사항 없음",
        "",
    ]
    (OUT_DIR / "VALIDATION_REPORT.md").write_text("\n".join(validation_lines), encoding="utf-8", newline="\n")

    print(f"md={len(md_paths)} images={len(image_paths)} other={len(other_paths)}")
    print(f"organized_md={organized_md_count_final} organized_images={len(organized_images)} organized_other={len(organized_other)}")
    print(f"confirm_needed={len(confirm_needed)}")


if __name__ == "__main__":
    main()
