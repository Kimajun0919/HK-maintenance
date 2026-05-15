from __future__ import annotations

import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "organized_maintenance_docs_simple"
REPORT = DOCS_DIR / "READABILITY_CLEANUP_REPORT.md"

DOC_INFO = "\ubb38\uc11c \uc815\ubcf4"
SUMMARY = "\uc694\uc57d"
BODY = "\ubcf8\ubb38"
IMAGE_PATHS = "\uc774\ubbf8\uc9c0 \uacbd\ub85c"
NEEDS_REVIEW = "\ud655\uc778 \ud544\uc694"
CLEAN_VALIDATION = "\uc815\ub9ac \uac80\uc99d"

SKIP_NAMES = {
    "README.md",
    "SIMPLIFY_CHANGELOG.md",
    "SIMPLIFY_VALIDATION_REPORT.md",
    "READABILITY_CLEANUP_REPORT.md",
    "READABILITY_FINAL_VALIDATION.md",
    "READABILITY_DOC_INFO_ORDER_REPORT.md",
    "HK_CUSTOMER_INFO_INDEX.md",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_content(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_numbered_sections(text: str) -> tuple[str, dict[int, tuple[str, str]]]:
    matches = list(re.finditer(r"^##\s+(\d+)\.\s+(.+?)\s*$", text, flags=re.M))
    preface = text[: matches[0].start()].strip() if matches else text.strip()
    sections: dict[int, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[number] = (title, text[start:end].strip())
    return preface, sections


def extract_fenced_markdown(text: str) -> str:
    match = re.search(r"````markdown\s*\n(?P<body>.*?)\n````", text, flags=re.S)
    if match:
        return match.group("body").strip()
    match = re.search(r"```markdown\s*\n(?P<body>.*?)\n```", text, flags=re.S)
    if match:
        return match.group("body").strip()
    return ""


def clean_detail(text: str) -> str:
    lines = []
    for raw in text.strip().splitlines():
        line = raw.strip()
        if line.startswith("\uc544\ub798 \ub0b4\uc6a9\uc740 \uc6d0\ubcf8 md \ubb38\uc11c\uc758 \ubcf8\ubb38 \uc804\uccb4\uc785\ub2c8\ub2e4."):
            continue
        lines.append(raw.rstrip())
    return normalize_content("\n".join(lines))


def clean_summary(text: str) -> str:
    keep: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\ub204\ub77d \uc5c6\uc774 \ubcf4\uc874\ud55c \uc815\ub9ac\ubcf8" in line:
            continue
        if "\uc608\uc0c1 \uae30\uc5c5\uba85\uc740" in line and "\ubb38\uc11c \uc720\ud615\uc740" in line:
            continue
        if "\uc774\ubbf8\uc9c0" in line and "\ubcf5\uc0ac" in line and "\uc5f0\uacb0" in line:
            continue
        keep.append(raw.rstrip())
    return normalize_content("\n".join(keep))


def clean_checks(text: str) -> str:
    keep: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "- \uc790\ub3d9 \uc815\ub9ac \uae30\uc900\uc0c1 \ubcc4\ub3c4 \ud655\uc778 \ud544\uc694 \uc0ac\ud56d \uc5c6\uc74c":
            continue
        if "\uc774\ubbf8\uc9c0 \ub0b4 \ud14d\uc2a4\ud2b8" in line and "\uc790\ub3d9 OCR" in line:
            continue
        keep.append(raw.rstrip())
    return normalize_content("\n".join(keep))


def clean_overview(text: str) -> str:
    keep: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "\uad00\ub828 \uc0ac\uc774\ud2b8: \uc6d0\ubcf8 \ub0b4\uc6a9 \ucc38\uc870" in line:
            continue
        if "\uad00\ub828 \uad00\ub9ac\uc790 URL: \uc6d0\ubcf8 \ub0b4\uc6a9 \ucc38\uc870" in line:
            continue
        keep.append(raw.rstrip())
    return normalize_content("\n".join(keep))


def image_summary(body: str) -> str:
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", body)
    if not refs:
        return ""
    return "\n".join(f"- \uc774\ubbf8\uc9c0 {idx}: `{ref}`" for idx, ref in enumerate(refs, 1))


def rebuild_doc(text: str) -> tuple[str | None, dict[str, str]]:
    preface, sections = split_numbered_sections(text)
    if 3 not in sections:
        return None, {"status": "skipped", "reason": "no detail section"}

    title = preface.strip() or "# Untitled"
    overview = clean_overview(sections.get(1, ("", ""))[1])
    summary = clean_summary(sections.get(2, ("", ""))[1])
    detail = clean_detail(sections[3][1])
    original = extract_fenced_markdown(sections.get(8, ("", ""))[1])
    compare_source = normalize_content(original or detail)

    compare_ok = normalize_content(detail) == compare_source
    if original and not compare_ok:
        return None, {"status": "skipped", "reason": "detail/original mismatch"}

    checks = clean_checks(sections.get(9, ("", ""))[1])
    images = image_summary(detail)

    parts = [title.strip()]
    if summary:
        parts.extend(["", f"## {SUMMARY}", "", summary])
    parts.extend(["", f"## {BODY}", "", detail])
    if images:
        parts.extend(["", f"## {IMAGE_PATHS}", "", images])
    if checks:
        parts.extend(["", f"## {NEEDS_REVIEW}", "", checks])
    parts.extend(
        [
            "",
            f"## {CLEAN_VALIDATION}",
            "",
            "- \ubcf8\ubb38\uc740 \uae30\uc874 `\uc0c1\uc138 \ub0b4\uc6a9` \uc6d0\ubb38\uc744 \uae30\uc900\uc73c\ub85c \uc720\uc9c0\ud588\uc2b5\ub2c8\ub2e4.",
            "- \uae30\uc874 `\uc6d0\ubcf8 \ubcf4\uc874 \ub0b4\uc6a9` \ube14\ub85d\uc774 \uc788\ub294 \ubb38\uc11c\ub294 \uc815\ub9ac \uc804 \ubcf8\ubb38\uacfc \uc6d0\ubcf8 \ubcf4\uc874 \ube14\ub85d\uc744 \ube44\uad50\ud588\uc2b5\ub2c8\ub2e4.",
            "- \ubc18\ubcf5 \uc548\ub0b4 \ubb38\uad6c\uc640 \uc911\ubcf5 \uc6d0\ubcf8 \ubcf4\uc874 \ube14\ub85d\ub9cc \uc81c\uac70\ud588\uc2b5\ub2c8\ub2e4.",
        ]
    )
    if overview:
        parts.extend(["", f"## {DOC_INFO}", "", overview])

    return normalize_content("\n".join(parts)) + "\n", {
        "status": "processed",
        "compare_ok": str(compare_ok),
        "had_original_block": str(bool(original)),
        "body_sha256": sha256_text(compare_source),
    }


def main() -> None:
    report_rows: list[dict[str, str]] = []
    processed = skipped = unchanged = 0

    for path in sorted(DOCS_DIR.rglob("*.md")):
        rel = path.relative_to(DOCS_DIR).as_posix()
        if path.name in SKIP_NAMES:
            continue
        before = path.read_text(encoding="utf-8", errors="replace")
        rebuilt, info = rebuild_doc(before)
        info["file"] = rel
        info["before_sha256"] = sha256_text(before)
        if rebuilt is None:
            skipped += 1
            report_rows.append(info)
            continue
        info["after_sha256"] = sha256_text(rebuilt)
        if rebuilt == before:
            unchanged += 1
        else:
            path.write_text(rebuilt, encoding="utf-8", newline="\n")
            processed += 1
        report_rows.append(info)

    report = [
        "# Readability Cleanup Report",
        "",
        f"- processed: {processed}",
        f"- unchanged: {unchanged}",
        f"- skipped: {skipped}",
        "",
        "## Validation Summary",
        "",
        "All processed files kept the pre-cleanup detail body unchanged. Files with an existing original preservation block were compared before rewrite.",
        "",
        "| file | status | original block | body compare | reason |",
        "|---|---|---:|---:|---|",
    ]
    for row in report_rows:
        report.append(
            "| {file} | {status} | {had_original_block} | {compare_ok} | {reason} |".format(
                file=row.get("file", ""),
                status=row.get("status", ""),
                had_original_block=row.get("had_original_block", ""),
                compare_ok=row.get("compare_ok", ""),
                reason=row.get("reason", ""),
            )
        )
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    print(f"processed={processed} unchanged={unchanged} skipped={skipped}")


if __name__ == "__main__":
    main()
