from __future__ import annotations


def _convert_docx_to_md(content: bytes) -> str:
    try:
        import io as _io
        from docx import Document
    except ImportError:
        return "# 변환 오류\n\n`python-docx` 패키지가 필요합니다. `pip install python-docx`"
    try:
        doc = Document(_io.BytesIO(content))
        lines: list[str] = []

        for para in doc.paragraphs:
            text = para.text.strip()
            style = para.style.name.lower() if para.style else ""
            if not text:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            if "heading 1" in style:
                lines.append(f"# {text}")
            elif "heading 2" in style:
                lines.append(f"## {text}")
            elif "heading 3" in style:
                lines.append(f"### {text}")
            elif "list" in style or "bullet" in style:
                lines.append(f"- {text}")
            else:
                lines.append(text)

        for table in doc.tables:
            if not table.rows:
                continue
            headers = [cell.text.strip().replace("|", "\\|") for cell in table.rows[0].cells]
            lines.append("")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for row in table.rows[1:]:
                cells = [cell.text.strip().replace("|", "\\|") for cell in row.cells]
                lines.append("| " + " | ".join(cells) + " |")
            lines.append("")

        return "\n".join(lines).strip()
    except Exception as exc:
        return f"# 변환 오류\n\n{exc}"


def _convert_pdf_to_md(content: bytes) -> str:
    try:
        import io as _io
        from pypdf import PdfReader
    except ImportError:
        return "# 변환 오류\n\n`pypdf` 패키지가 필요합니다. `pip install pypdf`"
    try:
        reader = PdfReader(_io.BytesIO(content))
        if not reader.pages:
            return "# 내용 없음\n\n페이지가 없습니다."
        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"## 페이지 {i + 1}\n\n{text}")
        if not pages:
            return "# 텍스트 추출 불가\n\n스캔된 이미지 PDF는 지원하지 않습니다."
        return "\n\n".join(pages)
    except Exception as exc:
        return f"# 변환 오류\n\n{exc}"
