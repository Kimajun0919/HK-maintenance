from __future__ import annotations

import os
import re
import io
import json
import mimetypes
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from fastapi import Request


from config import (
    ANTHROPIC_API_URL,
    APP_DIR,
    ASSET_MAX_SIZE_BYTES,
    ASSET_MAX_SIZE_MB,
    DEFAULT_CLAUDE_MODEL,
    DOCS_DIR,
    MAX_NEW_TOKENS,
    MODEL_NAME,
    SUPABASE_ASSETS_TABLE,
    SUPABASE_DOCS_TABLE,
    SUPABASE_ENABLED,
    SUPABASE_META_TABLE,
    USE_LLM,
)
from converters import _convert_docx_to_md, _convert_pdf_to_md
from models import AssetRecord, DocRecord, FolderRecord

from storage import (
    _db_asset_count,
    _db_asset_paths,
    _db_asset_record,
    _db_asset_total_bytes,
    _db_cascade_soft_delete_assets,
    _db_connect,
    _db_create_doc,
    _db_create_folder,
    _db_delete_folder,
    _db_doc_record,
    _db_folder_doc_count,
    _db_folder_exists,
    _db_folder_records,
    _db_permanent_delete_asset,
    _db_permanent_delete_doc,
    _db_rename_doc,
    _db_rename_folder,
    _db_restore_asset,
    _db_restore_doc,
    _db_soft_delete_asset,
    _db_soft_delete_doc,
    _db_trash_records,
    _db_update_doc,
    _db_update_folder_order,
    _db_upsert_asset,
    _doc_records,
    _file_asset_records,
    _file_folder_records,
)

import rag

def claude_answer(query: str, top_k: int, api_key: str, model: str) -> str:
    api_key = api_key.strip()
    model = (model or DEFAULT_CLAUDE_MODEL).strip()
    if not api_key:
        return "Claude API 키를 입력해야 합니다."

    results, context = rag.retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 작업명, 서버/계정/경로 같은 단어를 포함해 다시 질문해 주세요."

    sources = "\n".join(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}" for chunk, score in results)
    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 반드시 위 문서 근거 안의 내용만 사용하세요.
- 계정, 경로, 서버, 작업 절차, 주의사항은 원문 값을 임의로 바꾸지 마세요.
- 근거에 없으면 "확인 필요"라고 답하세요.
- 답변 마지막에 참고 문서 파일명을 bullet로 정리하세요.
"""
    payload = {
        "model": model,
        "max_tokens": MAX_NEW_TOKENS,
        "system": "당신은 HK 유지보수 문서 RAG 도우미입니다. 제공된 문서 근거만 바탕으로 한국어로 간결하고 정확하게 답변합니다.",
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"Claude API 오류({exc.code}): {body[:700]}"
    except Exception as exc:
        return f"Claude API 호출 실패: {exc}"

    parts = []
    for block in data.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")).strip())
    generated = "\n\n".join(part for part in parts if part)
    if not generated:
        generated = rag.source_based_answer(query, results)
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def openai_compatible_answer(query: str, top_k: int, api_key: str, base_url: str, model: str,
                             auth_header: str = "", chat_path: str = "") -> str:
    base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
    model = (model or "gpt-4o-mini").strip()
    chat_path = (chat_path or "/chat/completions").strip()
    if not chat_path.startswith("/"):
        chat_path = "/" + chat_path

    results, context = rag.retrieve(query, top_k)
    if not context:
        return "관련 문서를 찾지 못했습니다. 고객사명, 작업명, 서버/계정/경로 같은 단어를 포함해 다시 질문해 주세요."

    sources = "\n".join(f"- `{chunk.source}` / {chunk.title} / score={score:.3f}" for chunk, score in results)
    prompt = f"""질문:
{query}

문서 근거:
{context}

답변 조건:
- 반드시 위 문서 근거 안의 내용만 사용하세요.
- 계정, 경로, 서버, 작업 절차, 주의사항은 원문 값을 임의로 바꾸지 마세요.
- 근거에 없으면 "확인 필요"라고 답하세요.
- 답변 마지막에 참고 문서 파일명을 bullet로 정리하세요.
"""
    payload = {
        "model": model,
        "max_tokens": MAX_NEW_TOKENS,
        "messages": [
            {"role": "system", "content": "당신은 HK 유지보수 문서 RAG 도우미입니다. 제공된 문서 근거만 바탕으로 한국어로 간결하고 정확하게 답변합니다."},
            {"role": "user", "content": prompt},
        ],
    }
    headers: dict[str, str] = {"content-type": "application/json"}
    if api_key.strip():
        key = api_key.strip()
        if auth_header.strip():
            headers[auth_header.strip().lower()] = key
        else:
            headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"{base_url}{chat_path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return f"API 오류({exc.code}): {body[:700]}"
    except Exception as exc:
        return f"API 호출 실패: {exc}"

    choices = data.get("choices", [])
    generated = choices[0].get("message", {}).get("content", "").strip() if choices else ""
    if not generated:
        generated = rag.source_based_answer(query, results)
    return f"{generated}\n\n---\n참고 문서:\n{sources}"


def build_demo():
    import gradio as gr

    with gr.Blocks(title="HK Maintenance RAG Chatbot") as demo:
        gr.Markdown(
            f"""
# HK Maintenance RAG Chatbot

- 문서 경로: `{DOCS_DIR}`
- 문서 청크: `{len(rag.chunks)}`
- LLM: `{MODEL_NAME if USE_LLM else "비활성"}`
"""
        )
        if USE_LLM:
            gr.Markdown("검색 결과를 먼저 표시한 뒤, LLM 답변이 준비되면 같은 답변 영역을 업데이트합니다.")
        try:
            chatbot = gr.Chatbot(type="messages", height=520)
        except TypeError:
            chatbot = gr.Chatbot(height=520)
        data_model_name = getattr(getattr(chatbot, "data_model", None), "__name__", "")
        chat_format = "messages" if "Messages" in data_model_name else "tuples"
        query = gr.Textbox(label="질문", placeholder="예: 대한항공 VPN 접속 방법 알려줘")
        top_k = gr.Slider(label="검색 근거 수", minimum=2, maximum=8, value=5, step=1)
        generate_llm = gr.Checkbox(
            label="LLM 답변도 생성",
            value=False,
            interactive=USE_LLM,
            info="무료 CPU에서는 느리고 품질이 낮을 수 있습니다. 기본 답변은 검색 근거 기반입니다.",
        )
        gr.ClearButton([query, chatbot])

        def normalize_history(chat_history: list | None) -> list:
            chat_history = chat_history or []
            normalized: list = []
            if chat_format == "messages":
                for item in chat_history:
                    if isinstance(item, dict) and "role" in item and "content" in item:
                        normalized.append(item)
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        user_msg, assistant_msg = item
                        normalized.append({"role": "user", "content": str(user_msg)})
                        normalized.append({"role": "assistant", "content": str(assistant_msg)})
                return normalized

            for item in chat_history:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    normalized.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict) and item.get("role") == "user":
                    normalized.append((str(item.get("content", "")), ""))
                elif isinstance(item, dict) and item.get("role") == "assistant":
                    if normalized and normalized[-1][1] == "":
                        normalized[-1] = (normalized[-1][0], str(item.get("content", "")))
                    else:
                        normalized.append(("", str(item.get("content", ""))))
            return normalized

        def respond(message: str, chat_history: list, k: int, use_llm_for_question: bool):
            chat_history = normalize_history(chat_history)
            bot_message = rag.immediate_answer(message, int(k))
            if chat_format == "messages":
                chat_history = chat_history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": bot_message},
                ]
            else:
                chat_history = chat_history + [(message, bot_message)]
            yield "", chat_history

            if not USE_LLM or not use_llm_for_question:
                return

            llm_message = rag.llm_answer(message, int(k))
            combined = (
                f"{bot_message}\n\n"
                "---\n"
                "<details><summary>LLM 답변 보기</summary>\n\n"
                f"{llm_message}"
                "\n\n</details>"
            )
            if chat_format == "messages":
                chat_history[-1] = {"role": "assistant", "content": combined}
            else:
                chat_history[-1] = (message, combined)
            yield "", chat_history

        query.submit(respond, [query, chatbot, top_k, generate_llm], [query, chatbot])
    return demo


try:
    demo = build_demo()
except ModuleNotFoundError as exc:
    if exc.name != "gradio":
        raise
    demo = None

WEB_DIR = next(
    (
        path
        for path in (
            APP_DIR / "frontend",
            APP_DIR.parent / "frontend",
            APP_DIR / "web",
        )
        if path.exists()
    ),
    APP_DIR.parent / "frontend",
)


def _json_response(data, status_code: int = 200):
    from fastapi.responses import JSONResponse

    return JSONResponse(data, status_code=status_code)


def _safe_doc_path(source: str) -> Path | None:
    try:
        path = (DOCS_DIR / source).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if not path.exists() or path.suffix.lower() != ".md":
        return None
    return path


def _safe_new_doc_path(source: str) -> Path | None:
    normalized = urllib.parse.unquote(str(source or "")).replace("\\", "/").strip("/")
    if not normalized or normalized.startswith(".") or "/." in normalized:
        return None
    if not normalized.lower().endswith(".md"):
        normalized += ".md"
    try:
        path = (DOCS_DIR / normalized).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if path.name in {"README.md", "SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
        return None
    return path


def _safe_source_value(source: str, require_md: bool = True) -> str | None:
    normalized = urllib.parse.unquote(str(source or "")).replace("\\", "/").strip("/")
    if not normalized or normalized.startswith(".") or "/." in normalized:
        return None
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if require_md and not normalized.lower().endswith(".md"):
        normalized += ".md"
    if PurePosixPath(normalized).name in {"README.md", "SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
        return None
    return normalized


def _safe_folder_name(name: str) -> str | None:
    normalized = _slug_part(str(name or "").strip(), "")
    if not normalized or "/" in normalized or "\\" in normalized:
        return None
    if normalized.startswith(".") or normalized in {".", ".."}:
        return None
    return normalized


def _slug_part(value: str, fallback: str = "document") -> str:
    value = re.sub(r'[<>:"|?*\x00-\x1f]+', "", str(value or "")).strip()
    value = value.replace("\\", "/").split("/")[-1].strip()
    value = re.sub(r"\s+", "_", value)
    return value or fallback


def _doc_source_from_payload(payload: dict) -> str | None:
    source = str(payload.get("source", "")).strip()
    if source:
        return source
    customer = _slug_part(str(payload.get("customer", "")).strip(), "미분류")
    title = _slug_part(str(payload.get("title", "")).strip(), "새_문서")
    return f"{customer}/{title}.md"


def _is_system_doc(path: Path) -> bool:
    return path.name.startswith("READABILITY_") or path.name in {
        "README.md",
        "SIMPLIFY_CHANGELOG.md",
        "SIMPLIFY_VALIDATION_REPORT.md",
        "HK_CUSTOMER_INFO_INDEX.md",
    }


def _is_system_source(source: str) -> bool:
    name = Path(source).name
    return name.startswith("READABILITY_") or name in {
        "README.md",
        "SIMPLIFY_CHANGELOG.md",
        "SIMPLIFY_VALIDATION_REPORT.md",
        "HK_CUSTOMER_INFO_INDEX.md",
    }


def _safe_file_asset_path(rel_path: str) -> Path | None:
    """Validate and resolve an asset's relative path within DOCS_DIR (file mode only)."""
    try:
        resolved = (DOCS_DIR / rel_path).resolve()
        resolved.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    if resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return None
    return resolved


def _safe_asset_path(source: str, asset_path: str) -> Path | None:
    doc_path = _safe_doc_path(source)
    if doc_path is None:
        return None
    decoded_path = urllib.parse.unquote(asset_path).replace("\\", "/")
    try:
        path = (doc_path.parent / decoded_path).resolve()
        path.relative_to(DOCS_DIR)
    except (ValueError, RuntimeError):
        return None
    if path.exists() and path.is_file():
        return path

    images_dir = doc_path.parent / "images"
    if images_dir.exists():
        original_name = Path(decoded_path).name
        doc_key = re.sub(r"_\d{8}$", "", doc_path.stem)
        name_match = re.match(r"image(?:\s+(\d+))?\.[A-Za-z0-9]+$", original_name, flags=re.I)
        if name_match:
            number = name_match.group(1)
            patterns = (
                [f"{doc_key}_image_{number}_*.png", f"*image_{number}_*.png"]
                if number
                else [f"{doc_key}_image_*.png", f"{doc_key}_image.*", "*image_*.png"]
            )
            candidates = []
            for pattern in patterns:
                candidates = sorted(images_dir.glob(pattern))
                if candidates:
                    break
            if candidates:
                return candidates[0].resolve()
        direct_matches = sorted(images_dir.glob(f"*{Path(original_name).stem.replace(' ', '_')}*"))
        if direct_matches:
            return direct_matches[0].resolve()
    return None


def _asset_target_from_source(source: str, filename: str) -> tuple[str, str] | None:
    source_value = _safe_source_value(source)
    if source_value is None:
        return None
    source_parts = PurePosixPath(source_value).parts
    if len(source_parts) < 2:
        return None
    clean_name = _slug_part(Path(filename or "image.png").name, "image.png")
    if "." not in clean_name:
        clean_name += ".png"
    stem = PurePosixPath(source_value).stem
    unique = f"{int(time.time() * 1000)}_{clean_name}"
    asset_rel = (PurePosixPath(*source_parts[:-1]) / "images" / f"{stem}_{unique}").as_posix()
    markdown_rel = f"images/{stem}_{unique}"
    return asset_rel, markdown_rel


def _doc_asset_refs(source: str, content: str) -> set[str]:
    folder = PurePosixPath(source).parent
    refs: set[str] = set()
    for match in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', content or ""):
        raw = match.group(1).strip().split()[0].strip('"').strip("'")
        if not raw or raw.startswith("/") or raw.startswith("data:") or re.match(r"^(https?:)?//", raw, flags=re.I):
            continue
        refs.add((folder / PurePosixPath(raw)).as_posix())
    return refs


def _zip_filename(value: str) -> str:
    name = re.sub(r'[<>:"|?*\x00-\x1f]+', "_", value).strip(" ._")
    return name or "download"


def _safe_posix_parts(value: str) -> tuple[str, ...] | None:
    parts = PurePosixPath(value.replace("\\", "/")).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    if str(value).startswith(("/", "\\")):
        return None
    return parts


def _db_asset_record_for_request(source: str, asset_path: str) -> AssetRecord | None:
    source_parts = _safe_posix_parts(urllib.parse.unquote(source))
    asset_parts = _safe_posix_parts(urllib.parse.unquote(asset_path))
    if source_parts is None or asset_parts is None:
        return None

    doc_parent = PurePosixPath(*source_parts[:-1])
    direct_path = (doc_parent / PurePosixPath(*asset_parts)).as_posix()
    direct = _db_asset_record(direct_path)
    if direct is not None:
        return direct

    requested_name = PurePosixPath(*asset_parts).name
    for path in _db_asset_paths():
        if PurePosixPath(path).name == requested_name:
            return _db_asset_record(path)

    images_prefix = (doc_parent / "images").as_posix().strip("/")
    if images_prefix:
        images_prefix += "/"
    paths = _db_asset_paths(images_prefix)
    if not paths:
        return None

    original_name = PurePosixPath(*asset_parts).name
    doc_key = re.sub(r"_\d{8}$", "", PurePosixPath(*source_parts).stem)
    name_match = re.match(r"image(?:\s+(\d+))?\.[A-Za-z0-9]+$", original_name, flags=re.I)
    if name_match:
        number = name_match.group(1)
        if number:
            patterns = (f"{doc_key}_image_{number}_", f"image_{number}_")
        else:
            patterns = (f"{doc_key}_image_", "image_")
        for path in paths:
            filename = PurePosixPath(path).name
            if any(pattern in filename for pattern in patterns):
                return _db_asset_record(path)

    original_stem = PurePosixPath(original_name).stem.replace(" ", "_")
    for path in paths:
        if original_stem and original_stem in PurePosixPath(path).stem:
            return _db_asset_record(path)
    return None


def docs_index() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for record in _doc_records():
        name = Path(record.source).name
        if name in {"SIMPLIFY_CHANGELOG.md", "SIMPLIFY_VALIDATION_REPORT.md"}:
            continue
        items.append({"source": record.source, "title": record.title, "customer": record.customer, "updatedAt": record.updated_at})
    return items


def folders_index() -> list[dict[str, str | int]]:
    records = _db_folder_records() if SUPABASE_ENABLED else _file_folder_records()
    doc_counts: Counter[str] = Counter(record.customer for record in _doc_records())
    seen = {record.name for record in records}
    for folder in sorted(doc_counts):
        if folder and folder not in seen:
            records.append(FolderRecord(name=folder, sort_order=len(records)))
            seen.add(folder)
    return [
        {"name": record.name, "sortOrder": record.sort_order, "docCount": doc_counts.get(record.name, 0)}
        for record in records
    ]


def create_api_app():
    from fastapi import FastAPI, Query
    from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
    from fastapi.staticfiles import StaticFiles

    api_app = FastAPI(title="HK Maintenance Portal")
    if WEB_DIR.exists():
        api_app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")

    @api_app.get("/", response_class=HTMLResponse)
    def home():
        index = WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return HTMLResponse("<h1>HK Maintenance Portal</h1><p>web/index.html is missing.</p>")

    @api_app.get("/healthz")
    def healthz():
        return {"ok": True, "docs_dir": str(DOCS_DIR), "chunks": len(rag.chunks), "llm": MODEL_NAME if USE_LLM else "disabled"}

    @api_app.get("/api/meta")
    def api_meta():
        asset_total_bytes = _db_asset_total_bytes() if SUPABASE_ENABLED else 0
        return {
            "docsDir": str(DOCS_DIR),
            "storage": "supabase" if SUPABASE_ENABLED else "files",
            "chunkCount": len(rag.chunks),
            "docCount": len(docs_index()),
            "assetCount": _db_asset_count() if SUPABASE_ENABLED else len(_file_asset_records()),
            "assetTotalBytes": asset_total_bytes,
            "assetMaxSizeBytes": ASSET_MAX_SIZE_BYTES,
            "llm": MODEL_NAME if USE_LLM else "disabled",
            "claudeDefaultModel": DEFAULT_CLAUDE_MODEL,
        }

    @api_app.get("/api/docs")
    def api_docs():
        return {"docs": docs_index(), "folders": folders_index()}

    @api_app.get("/api/folders")
    def api_folders():
        return {"folders": folders_index()}

    @api_app.post("/api/folder")
    async def api_create_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        name = _safe_folder_name(str(payload.get("name", "")))
        if not name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if SUPABASE_ENABLED:
            if _db_folder_exists(name):
                return _json_response({"error": "folder already exists"}, status_code=409)
            _db_create_folder(name)
        else:
            path = (DOCS_DIR / name).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if path.exists():
                return _json_response({"error": "folder already exists"}, status_code=409)
            path.mkdir(parents=True)
        return {"folder": name}

    @api_app.put("/api/folder")
    async def api_update_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        old_name = _safe_folder_name(str(payload.get("name", "")))
        new_name = _safe_folder_name(str(payload.get("newName", "")))
        if not old_name or not new_name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if old_name == new_name:
            return {"folder": new_name}
        if SUPABASE_ENABLED:
            if not _db_folder_exists(old_name):
                return _json_response({"error": "folder not found"}, status_code=404)
            if _db_folder_exists(new_name):
                return _json_response({"error": "folder already exists"}, status_code=409)
            _db_rename_folder(old_name, new_name)
        else:
            old_path = (DOCS_DIR / old_name).resolve()
            new_path = (DOCS_DIR / new_name).resolve()
            try:
                old_path.relative_to(DOCS_DIR)
                new_path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if not old_path.exists() or not old_path.is_dir():
                return _json_response({"error": "folder not found"}, status_code=404)
            if new_path.exists():
                return _json_response({"error": "folder already exists"}, status_code=409)
            old_path.rename(new_path)
        rag.refresh_index()
        return {"folder": new_name}

    @api_app.put("/api/folders/order")
    async def api_update_folder_order(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        names = [_safe_folder_name(str(name)) for name in payload.get("folders", [])]
        if not names or any(name is None for name in names):
            return _json_response({"error": "invalid folder order"}, status_code=400)
        if SUPABASE_ENABLED:
            _db_update_folder_order([str(name) for name in names])
        return {"folders": folders_index()}

    @api_app.delete("/api/folder")
    async def api_delete_folder(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        name = _safe_folder_name(str(payload.get("name", "")))
        if not name:
            return _json_response({"error": "invalid folder name"}, status_code=400)
        if SUPABASE_ENABLED:
            if not _db_folder_exists(name):
                return _json_response({"error": "folder not found"}, status_code=404)
            if _db_folder_doc_count(name) > 0:
                return _json_response({"error": "folder is not empty"}, status_code=409)
            _db_delete_folder(name)
        else:
            path = (DOCS_DIR / name).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid folder name"}, status_code=400)
            if not path.exists() or not path.is_dir():
                return _json_response({"error": "folder not found"}, status_code=404)
            if any(path.iterdir()):
                return _json_response({"error": "folder is not empty"}, status_code=409)
            path.rmdir()
        return {"ok": True, "folder": name}

    @api_app.get("/api/doc")
    def api_doc(source: str = Query(...)):
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            return {"source": record.source, "title": record.title, "content": record.content}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        return {"source": source, "title": path.stem, "content": path.read_text(encoding="utf-8", errors="replace")}

    @api_app.post("/api/doc")
    async def api_create_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = _doc_source_from_payload(payload)
        path = _safe_new_doc_path(source or "")
        if path is None:
            return _json_response({"error": "invalid document path"}, status_code=400)
        rel = path.relative_to(DOCS_DIR).as_posix()
        if SUPABASE_ENABLED and _db_doc_record(rel) is not None:
            return _json_response({"error": "document already exists"}, status_code=409)
        if not SUPABASE_ENABLED and path.exists():
            return _json_response({"error": "document already exists"}, status_code=409)
        content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n").strip()
        if not content:
            title = path.stem.replace("_", " ")
            content = f"# {title}\n\n## 본문\n\n"
        content = content.rstrip() + "\n"
        if SUPABASE_ENABLED:
            parts = Path(rel).parts
            if parts and not _db_folder_exists(parts[0]):
                _db_create_folder(parts[0])
            _db_create_doc(
                DocRecord(
                    source=rel,
                    title=path.stem,
                    customer=parts[0] if parts else "",
                    content=content,
                )
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
        rag.refresh_index()
        return {"source": rel, "title": path.stem, "content": content}

    @api_app.put("/api/doc")
    async def api_update_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = str(payload.get("source", "")).strip()
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            if _is_system_source(source):
                return _json_response({"error": "system document cannot be edited"}, status_code=403)
            content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n")
            if not content.strip():
                return _json_response({"error": "content is empty"}, status_code=400)
            content = content.rstrip() + "\n"
            _db_update_doc(source, content)
            rag.refresh_index()
            updated = _db_doc_record(source)
            return {"source": source, "title": record.title, "content": updated.content if updated else content}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be edited"}, status_code=403)
        content = str(payload.get("content", "")).replace("\r\n", "\n").replace("\r", "\n")
        if not content.strip():
            return _json_response({"error": "content is empty"}, status_code=400)
        path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")
        rag.refresh_index()
        return {"source": source, "title": path.stem, "content": path.read_text(encoding="utf-8", errors="replace")}

    @api_app.put("/api/doc/rename")
    async def api_rename_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = _safe_source_value(str(payload.get("source", "")))
        folder = _safe_folder_name(str(payload.get("folder", "")))
        title = _slug_part(str(payload.get("title", "")).strip(), "")
        if not source or not folder or not title:
            return _json_response({"error": "invalid document name"}, status_code=400)
        new_source = _safe_source_value(f"{folder}/{title}.md")
        if not new_source:
            return _json_response({"error": "invalid document path"}, status_code=400)
        if _is_system_source(source):
            return _json_response({"error": "system document cannot be renamed"}, status_code=403)
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            existing = _db_doc_record(new_source)
            if existing is not None and new_source != source:
                return _json_response({"error": "document already exists"}, status_code=409)
            if not _db_folder_exists(folder):
                _db_create_folder(folder)
            renamed = _db_rename_doc(source, new_source, Path(new_source).stem, folder)
            rag.refresh_index()
            return {"source": renamed.source, "title": renamed.title, "content": renamed.content}

        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be renamed"}, status_code=403)
        new_path = _safe_new_doc_path(new_source)
        if new_path is None:
            return _json_response({"error": "invalid document path"}, status_code=400)
        if new_path.exists() and new_path != path:
            return _json_response({"error": "document already exists"}, status_code=409)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        path.rename(new_path)
        rag.refresh_index()
        rel = new_path.relative_to(DOCS_DIR).as_posix()
        return {"source": rel, "title": new_path.stem, "content": new_path.read_text(encoding="utf-8", errors="replace")}

    @api_app.delete("/api/doc")
    async def api_delete_doc(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        source = str(payload.get("source", "")).strip()
        if SUPABASE_ENABLED:
            record = _db_doc_record(source)
            if record is None:
                return _json_response({"error": "document not found"}, status_code=404)
            if _is_system_source(source):
                return _json_response({"error": "system document cannot be deleted"}, status_code=403)
            _db_cascade_soft_delete_assets(source, record.content)
            _db_soft_delete_doc(source)
            rag.refresh_index()
            return {"ok": True, "source": source}
        path = _safe_doc_path(source)
        if path is None:
            return _json_response({"error": "document not found"}, status_code=404)
        if _is_system_doc(path):
            return _json_response({"error": "system document cannot be deleted"}, status_code=403)
        path.unlink()
        rag.refresh_index()
        return {"ok": True, "source": source}

    @api_app.get("/api/asset")
    def api_asset(source: str = Query(...), path: str = Query(...)):
        if SUPABASE_ENABLED:
            asset_record = _db_asset_record_for_request(source, path)
            if asset_record is None:
                return _json_response({"error": "asset not found"}, status_code=404)
            return Response(content=asset_record.content, media_type=asset_record.mime_type)
        asset = _safe_asset_path(source, path)
        if asset is None:
            return _json_response({"error": "asset not found"}, status_code=404)
        return FileResponse(asset)

    @api_app.post("/api/download")
    async def api_download(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)

        folders = [name for name in (_safe_folder_name(str(item)) for item in payload.get("folders", [])) if name]
        files = [source for source in (_safe_source_value(str(item)) for item in payload.get("files", [])) if source]
        if not folders and not files:
            return _json_response({"error": "download selection is empty"}, status_code=400)

        buffer = io.BytesIO()
        added: set[str] = set()

        def write_zip(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
            zip_name = PurePosixPath(name).as_posix().lstrip("/")
            if not zip_name or zip_name in added:
                return
            added.add(zip_name)
            zf.writestr(zip_name, data)

        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if SUPABASE_ENABLED:
                records = _doc_records()
                selected_docs = [
                    record
                    for record in records
                    if record.source in files or any(record.source == folder or record.source.startswith(folder + "/") for folder in folders)
                ]
                for record in selected_docs:
                    write_zip(zf, record.source, record.content.encode("utf-8"))
                asset_paths = set()
                for folder in folders:
                    asset_paths.update(_db_asset_paths(folder + "/"))
                for record in selected_docs:
                    asset_paths.update(_doc_asset_refs(record.source, record.content))
                for asset_path in sorted(asset_paths):
                    asset = _db_asset_record(asset_path)
                    if asset is not None:
                        write_zip(zf, asset.path, asset.content)
            else:
                for folder in folders:
                    folder_path = (DOCS_DIR / folder).resolve()
                    try:
                        folder_path.relative_to(DOCS_DIR)
                    except ValueError:
                        continue
                    if folder_path.exists() and folder_path.is_dir():
                        for path in sorted(folder_path.rglob("*")):
                            if path.is_file():
                                write_zip(zf, path.relative_to(DOCS_DIR).as_posix(), path.read_bytes())
                for source in files:
                    path = _safe_doc_path(source)
                    if path is not None:
                        content = path.read_text(encoding="utf-8", errors="replace")
                        write_zip(zf, path.relative_to(DOCS_DIR).as_posix(), content.encode("utf-8"))
                        for asset_rel in _doc_asset_refs(source, content):
                            asset_path = _safe_file_asset_path(asset_rel)
                            if asset_path is not None:
                                write_zip(zf, asset_rel, asset_path.read_bytes())

        if not added:
            return _json_response({"error": "selected files were not found"}, status_code=404)

        label = folders[0] if len(folders) == 1 and not files else "selected"
        filename = _zip_filename(f"hk-maintenance-{label}.zip")
        headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}"}
        return Response(content=buffer.getvalue(), media_type="application/zip", headers=headers)

    @api_app.post("/api/asset")
    async def api_upload_asset(request: Request):
        form = await request.form()
        source = str(form.get("source", "")).strip()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename"):
            return _json_response({"error": "file is required"}, status_code=400)
        target = _asset_target_from_source(source, str(upload.filename))
        if target is None:
            return _json_response({"error": "valid document source is required"}, status_code=400)
        asset_rel, markdown_rel = target
        content = await upload.read()
        if not content:
            return _json_response({"error": "file is empty"}, status_code=400)
        if len(content) > ASSET_MAX_SIZE_BYTES:
            limit_mb = ASSET_MAX_SIZE_MB if ASSET_MAX_SIZE_MB == int(ASSET_MAX_SIZE_MB) else ASSET_MAX_SIZE_MB
            return _json_response({"error": f"파일이 너무 큽니다. 최대 {int(limit_mb) if limit_mb == int(limit_mb) else limit_mb}MB까지 업로드할 수 있습니다."}, status_code=413)
        mime_type = getattr(upload, "content_type", None) or mimetypes.guess_type(str(upload.filename))[0] or "application/octet-stream"
        if not mime_type.startswith("image/"):
            return _json_response({"error": "only image uploads are supported"}, status_code=400)
        if SUPABASE_ENABLED:
            _db_upsert_asset(AssetRecord(path=asset_rel, mime_type=mime_type, content=content))
        else:
            path = (DOCS_DIR / asset_rel).resolve()
            try:
                path.relative_to(DOCS_DIR)
            except ValueError:
                return _json_response({"error": "invalid asset path"}, status_code=400)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        url = "/api/asset?source=" + urllib.parse.quote(source) + "&path=" + urllib.parse.quote(markdown_rel)
        return {"path": markdown_rel, "url": url}

    @api_app.post("/api/convert")
    async def api_convert(request: Request):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "filename"):
            return _json_response({"error": "file is required"}, status_code=400)
        filename = str(upload.filename or "")
        ext = Path(filename).suffix.lower()
        if ext not in {".md", ".docx", ".pdf"}:
            return _json_response({"error": ".md, .docx, .pdf 파일만 지원합니다."}, status_code=400)
        raw = await upload.read()
        if not raw:
            return _json_response({"error": "파일이 비어 있습니다."}, status_code=400)
        if ext == ".md":
            content = raw.decode("utf-8", errors="replace")
        elif ext == ".docx":
            content = _convert_docx_to_md(raw)
        else:
            content = _convert_pdf_to_md(raw)
        title = Path(filename).stem
        return {"title": title, "content": content}

    @api_app.delete("/api/asset")
    async def api_delete_asset(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        path = str(payload.get("path", "")).strip()
        if not path:
            return _json_response({"error": "path is required"}, status_code=400)
        if SUPABASE_ENABLED:
            if _db_asset_record(path) is None:
                return _json_response({"error": "asset not found"}, status_code=404)
            _db_soft_delete_asset(path)
            return {"ok": True, "path": path}
        asset_file = _safe_file_asset_path(path)
        if asset_file is None:
            return _json_response({"error": "asset not found"}, status_code=404)
        asset_file.unlink()
        return {"ok": True, "path": path}

    @api_app.get("/api/trash")
    def api_trash():
        if not SUPABASE_ENABLED:
            return {"docs": [], "assets": []}
        return _db_trash_records()

    @api_app.post("/api/trash/restore")
    async def api_trash_restore(request: Request):
        if not SUPABASE_ENABLED:
            return _json_response({"error": "trash requires Supabase storage"}, status_code=400)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        item_type = str(payload.get("type", "")).strip()
        key = str(payload.get("key", "")).strip()
        if not key:
            return _json_response({"error": "key is required"}, status_code=400)
        if item_type == "doc":
            _db_restore_doc(key)
            rag.refresh_index()
        elif item_type == "asset":
            _db_restore_asset(key)
        else:
            return _json_response({"error": "type must be 'doc' or 'asset'"}, status_code=400)
        return {"ok": True, "type": item_type, "key": key}

    @api_app.delete("/api/trash")
    async def api_trash_delete(request: Request):
        if not SUPABASE_ENABLED:
            return _json_response({"error": "trash requires Supabase storage"}, status_code=400)
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        item_type = str(payload.get("type", "")).strip()
        key = str(payload.get("key", "")).strip()
        if item_type == "all":
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"delete from {SUPABASE_DOCS_TABLE} where deleted_at is not null")
                    cur.execute(f"delete from {SUPABASE_ASSETS_TABLE} where deleted_at is not null")
            rag.refresh_index()
            return {"ok": True}
        if not key:
            return _json_response({"error": "key is required"}, status_code=400)
        if item_type == "doc":
            _db_permanent_delete_doc(key)
            rag.refresh_index()
        elif item_type == "asset":
            _db_permanent_delete_asset(key)
        else:
            return _json_response({"error": "type must be 'doc', 'asset', or 'all'"}, status_code=400)
        return {"ok": True, "type": item_type, "key": key}

    @api_app.get("/api/search")
    def api_search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=10)):
        results, _context = rag.retrieve(q, top_k)
        return {
            "query": q,
            "answer": rag.source_based_answer(q, results),
            "results": [
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "score": round(score, 4),
                    "snippet": re.sub(r"\s+", " ", chunk.text).strip()[:700],
                }
                for chunk, score in results
            ],
        }

    @api_app.post("/api/chat")
    async def api_chat(request: Request):
        try:
            payload = await request.json()
        except json.JSONDecodeError:
            return _json_response({"error": "invalid json"}, status_code=400)
        query = str(payload.get("query", "")).strip()
        top_k = max(1, min(int(payload.get("topK", 5)), 10))
        use_llm = bool(payload.get("useLlm", False))
        if not query:
            return _json_response({"error": "query is required"}, status_code=400)
        provider = str(payload.get("provider", "local")).strip().lower()
        if provider == "claude":
            response = claude_answer(
                query,
                top_k,
                str(payload.get("apiKey", "")),
                str(payload.get("model", DEFAULT_CLAUDE_MODEL)),
            )
        elif provider == "openai":
            response = openai_compatible_answer(
                query,
                top_k,
                str(payload.get("apiKey", "")),
                str(payload.get("baseUrl", "https://api.openai.com/v1")),
                str(payload.get("model", "gpt-4o-mini")),
                auth_header=str(payload.get("authHeader", "")),
                chat_path=str(payload.get("chatPath", "")),
            )
        elif provider == "quick":
            response = rag.immediate_answer(query, top_k)
        else:
            response = rag.llm_answer(query, top_k) if USE_LLM else rag.immediate_answer(query, top_k)
        results, _context = rag.retrieve(query, top_k)
        return {
            "query": query,
            "answer": response,
            "results": [
                {
                    "source": chunk.source,
                    "title": chunk.title,
                    "score": round(score, 4),
                    "snippet": re.sub(r"\s+", " ", chunk.text).strip()[:700],
                }
                for chunk, score in results
            ],
        }

    @api_app.get("/robots.txt")
    def robots_txt():
        return PlainTextResponse("User-agent: *\nDisallow: /\n")

    # Existing Gradio chatbot is intentionally not mounted in the portal.
    # if demo is not None:
    #     api_app = gr.mount_gradio_app(api_app, demo, path="/chat")
    return api_app


app = create_api_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("APP_PORT", "7860")))

