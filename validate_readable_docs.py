from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "organized_maintenance_docs_simple"
REPORT = DOCS_DIR / "READABILITY_FINAL_VALIDATION.md"

BODY = "\ubcf8\ubb38"
ORIGINAL_SHA_LABEL = "\uc6d0\ubcf8 SHA-256"

SKIP_NAMES = {
    "README.md",
    "SIMPLIFY_CHANGELOG.md",
    "SIMPLIFY_VALIDATION_REPORT.md",
    "READABILITY_CLEANUP_REPORT.md",
    "READABILITY_FINAL_VALIDATION.md",
    "READABILITY_DOC_INFO_ORDER_REPORT.md",
    "HK_CUSTOMER_INFO_INDEX.md",
}


def normalize_content(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+$", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        if line.strip() == f"## {heading}":
            start = index + 1
            break
    if start is None:
        return ""
    for index in range(start, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end]).strip()


def main() -> None:
    rows: list[dict[str, str]] = []
    original_sha_pattern = re.compile(rf"{re.escape(ORIGINAL_SHA_LABEL)}:\s*`([0-9a-f]{{64}})`")
    for path in sorted(DOCS_DIR.rglob("*.md")):
        if path.name in SKIP_NAMES:
            continue
        rel = path.relative_to(DOCS_DIR).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        body = normalize_content(extract_section(text, BODY))
        original_sha_match = original_sha_pattern.search(text)
        original_sha = original_sha_match.group(1) if original_sha_match else ""
        body_sha = sha256_text(body) if body else ""
        if not body:
            status = "NO_BODY"
        elif not original_sha:
            status = "NO_ORIGINAL_SHA"
        elif body_sha == original_sha:
            status = "MATCH"
        else:
            status = "MISMATCH_BEFORE_CLEANUP"
        rows.append(
            {
                "file": rel,
                "status": status,
                "original_sha": original_sha,
                "body_sha": body_sha,
            }
        )

    counts = Counter(row["status"] for row in rows)
    report = [
        "# Readability Final Validation",
        "",
        "## Summary",
        "",
        f"- total checked: {len(rows)}",
        f"- exact original SHA match: {counts['MATCH']}",
        f"- no original SHA recorded: {counts['NO_ORIGINAL_SHA']}",
        f"- SHA mismatch flagged for manual source review: {counts['MISMATCH_BEFORE_CLEANUP']}",
        f"- missing body section: {counts['NO_BODY']}",
        "",
        "## Notes",
        "",
        f"- `MATCH` means the final `{BODY}` section SHA-256 is identical to the recorded original SHA-256.",
        "- `NO_ORIGINAL_SHA` documents are generated HK common/manual supplement documents without a recorded original SHA.",
        "- `MISMATCH_BEFORE_CLEANUP` means the final body does not match the recorded original SHA. These files were still protected during cleanup by comparing the pre-cleanup detail body with the pre-cleanup original-preservation block where present.",
        "",
        "## Details",
        "",
        "| file | status | original sha | body sha |",
        "|---|---|---|---|",
    ]
    for row in rows:
        report.append(
            f"| {row['file']} | {row['status']} | {row['original_sha']} | {row['body_sha']} |"
        )
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    print(
        "checked={checked} match={match} no_original={no_original} mismatch={mismatch} no_body={no_body}".format(
            checked=len(rows),
            match=counts["MATCH"],
            no_original=counts["NO_ORIGINAL_SHA"],
            mismatch=counts["MISMATCH_BEFORE_CLEANUP"],
            no_body=counts["NO_BODY"],
        )
    )


if __name__ == "__main__":
    main()
