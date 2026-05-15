from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "organized_maintenance_docs"
OUT_DIR = ROOT / "organized_maintenance_docs_simple"

MANAGEMENT_FILES = {
    "README.md",
    "CHANGELOG.md",
    "FILE_INVENTORY.md",
    "VALIDATION_REPORT.md",
}

COMMON_GROUPS = {
    "보고서": "공통자료/보고서",
    "링크_모음": "공통자료/링크모음",
    "대량메일_레몬메일": "공통자료/대량메일_레몬메일",
    "99_기타_미분류": "99_기타_미분류",
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def target_base(company: str) -> Path:
    mapped = COMMON_GROUPS.get(company)
    if mapped:
        return OUT_DIR / mapped
    return OUT_DIR / company


def simplify_doc_name(filename: str, company: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(rf"^{re.escape(company)}_", "", stem)
    stem = re.sub(r"^(유지보수매뉴얼|관리자계정|서버도메인|유지보수이력|작업팁|오류대응|기타미분류)_", "", stem)
    stem = re.sub(r"_20260514$", "", stem)
    if not stem or stem == company:
        stem = "유지보수정보"
    return f"{company}_{stem}_20260514.md"


def rewrite_image_links(text: str) -> str:
    text = re.sub(r"\]\(\./\.\./07_이미지_자료/([^)]+)\)", r"](./images/\1)", text)
    text = re.sub(r"`\./\.\./07_이미지_자료/([^`]+)`", r"`./images/\1`", text)
    return text


def copy_company(company_dir: Path) -> list[tuple[str, str, str]]:
    company = company_dir.name
    base = target_base(company)
    base.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str]] = []

    image_dir = company_dir / "07_이미지_자료"
    if image_dir.exists():
        images = [p for p in image_dir.rglob("*") if p.is_file()]
        if images:
            target_images = base / "images"
            target_images.mkdir(parents=True, exist_ok=True)
            for image in images:
                dst = unique_path(target_images / image.name)
                shutil.copy2(image, dst)
                rows.append((rel(image), rel(dst), "이미지 복사 및 images 폴더로 단순화"))

    for md in company_dir.rglob("*.md"):
        if md.parent.name == "07_이미지_자료":
            continue
        section = md.parent.name
        text = md.read_text(encoding="utf-8")
        text = rewrite_image_links(text)
        simplified_name = simplify_doc_name(md.name, company)
        dst = unique_path(base / simplified_name)
        dst.write_text(text, encoding="utf-8", newline="\n")
        rows.append((rel(md), rel(dst), f"{section} 하위 문서를 기업 폴더 루트로 이동"))

    return rows


def write_readme(rows: list[tuple[str, str, str]]) -> None:
    company_dirs = sorted([p for p in OUT_DIR.iterdir() if p.is_dir() and p.name != "공통자료"], key=lambda p: p.name)
    common_dirs = sorted((OUT_DIR / "공통자료").iterdir(), key=lambda p: p.name) if (OUT_DIR / "공통자료").exists() else []
    md_count = len(list(OUT_DIR.rglob("*.md")))
    image_count = len([p for p in OUT_DIR.rglob("*") if p.is_file() and p.parent.name == "images"])

    company_lines = "\n".join(f"- `{p.name}/`" for p in company_dirs)
    common_lines = "\n".join(f"- `공통자료/{p.name}/`" for p in common_dirs) or "- 없음"
    readme = f"""# 유지보수 문서 간소화 정리본

## 1. 개요

이 폴더는 `organized_maintenance_docs`의 표준형 정리본을 실제 사용 기준으로 다시 단순화한 버전입니다.

빈 섹션 폴더를 제거하고, 기업별 문서는 기업 폴더 루트에 배치했습니다. 이미지는 기업별 `images/` 폴더에 모았습니다.

## 2. 구조

```text
organized_maintenance_docs_simple/
  기업명/
    기업명_주제_20260514.md
    images/
  공통자료/
    보고서/
    링크모음/
    대량메일_레몬메일/
  99_기타_미분류/
```

## 3. 수량

| 항목 | 수량 |
|---|---:|
| md 문서 | {md_count} |
| 이미지 | {image_count} |
| 기업/분류 폴더 | {len(company_dirs)} |
| 공통자료 폴더 | {len(common_dirs)} |

## 4. 기업/분류 목록

{company_lines}

## 5. 공통자료 목록

{common_lines}

## 6. 사용 방법

1. 기업명 폴더에서 필요한 문서를 바로 확인합니다.
2. 이미지가 있는 기업은 같은 폴더의 `images/`를 확인합니다.
3. 보고서, 링크 모음, 대량메일 자료는 `공통자료/`에서 확인합니다.
4. 분류가 불확실한 문서는 `99_기타_미분류/`를 확인합니다.

## 7. 보존 원칙

- 이 간소화본은 기존 정리본의 md 내용을 삭제하지 않고 복사했습니다.
- 각 md의 원본 경로, 원본 파일명, 원본 SHA-256, `## 8. 원본 보존 내용`은 유지했습니다.
- 기존 `organized_maintenance_docs`와 `original_backup`은 변경하지 않았습니다.
"""
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8", newline="\n")

    index_lines = [
        "# 간소화 변경 내역",
        "",
        "| 번호 | 기존 정리본 경로 | 간소화 경로 | 변경 내용 |",
        "|---:|---|---|---|",
    ]
    for i, (src, dst, note) in enumerate(rows, 1):
        index_lines.append(f"| {i} | `{src}` | `{dst}` | {note} |")
    (OUT_DIR / "SIMPLIFY_CHANGELOG.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8", newline="\n")


def write_validation(rows: list[tuple[str, str, str]]) -> None:
    source_md = [p for p in SOURCE_DIR.rglob("*.md") if p.name not in MANAGEMENT_FILES]
    source_images = [p for p in SOURCE_DIR.rglob("*") if p.is_file() and p.parent.name == "07_이미지_자료"]
    out_md = [p for p in OUT_DIR.rglob("*.md") if p.name not in {"README.md", "SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}]
    out_images = [p for p in OUT_DIR.rglob("*") if p.is_file() and p.parent.name == "images"]
    empty_dirs = [p for p in OUT_DIR.rglob("*") if p.is_dir() and not any(p.iterdir())]

    report = f"""# 간소화 정리본 검증 보고서

## 1. 파일 수 검증

| 항목 | 기존 정리본 | 간소화본 | 상태 |
|---|---:|---:|---|
| md 문서 | {len(source_md)} | {len(out_md)} | {'정상' if len(source_md) == len(out_md) else '확인 필요'} |
| 이미지 | {len(source_images)} | {len(out_images)} | {'정상' if len(source_images) == len(out_images) else '확인 필요'} |
| 빈 폴더 | - | {len(empty_dirs)} | {'정상' if not empty_dirs else '확인 필요'} |

## 2. 구조 변경 기준

- 기업별 표준 섹션 폴더 중 빈 폴더는 생성하지 않았습니다.
- 문서는 기업 폴더 루트로 이동했습니다.
- 이미지는 기업별 `images/` 폴더에 모았습니다.
- 기업이 아닌 `보고서`, `링크_모음`, `대량메일_레몬메일`은 `공통자료/`로 이동했습니다.

## 3. 내용 보존 검증

- 기존 정리 md의 본문을 복사하고 이미지 링크 경로만 간소화본 구조에 맞게 변경했습니다.
- 각 md에 포함된 원본 경로, 원본 파일명, 원본 SHA-256, 원본 보존 내용은 유지했습니다.

## 4. 확인 필요 사항

- 자동 분류 자체는 기존 정리본의 결과를 따랐습니다.
- 이미지 내부 OCR은 수행하지 않았습니다.
"""
    (OUT_DIR / "SIMPLIFY_VALIDATION_REPORT.md").write_text(report, encoding="utf-8", newline="\n")


def main() -> None:
    if not SOURCE_DIR.exists():
        raise SystemExit("organized_maintenance_docs 폴더가 없습니다.")
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    all_rows: list[tuple[str, str, str]] = []
    for company_dir in sorted([p for p in SOURCE_DIR.iterdir() if p.is_dir()], key=lambda p: p.name):
        all_rows.extend(copy_company(company_dir))

    write_readme(all_rows)
    write_validation(all_rows)

    md_count = len(list(OUT_DIR.rglob("*.md")))
    image_count = len([p for p in OUT_DIR.rglob("*") if p.is_file() and p.parent.name == "images"])
    empty_count = len([p for p in OUT_DIR.rglob("*") if p.is_dir() and not any(p.iterdir())])
    print(f"simple_md={md_count}")
    print(f"simple_images={image_count}")
    print(f"empty_dirs={empty_count}")


if __name__ == "__main__":
    main()
