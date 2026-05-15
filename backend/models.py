from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    text: str
    source: str
    title: str


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
