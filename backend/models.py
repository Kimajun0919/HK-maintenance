from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str
    title: str
    document_id: str | None = None
    chunk_id: str | None = None
    heading: str | None = None
    filename: str | None = None
    folder: str | None = None
    updated_at: str | None = None
    normalized_body: str = ""
    compact_body: str = ""


@dataclass
class DocRecord:
    source: str
    title: str
    customer: str
    content: str
    updated_at: str | None = None


@dataclass
class AssetRecord:
    path: str
    mime_type: str
    content: bytes


@dataclass
class FolderRecord:
    name: str
    sort_order: int
