# HK Maintenance RAG v2

v2 is an experimental RAG path for Korean retrieval quality.

The production web service must still fit small Render instances, so v2 keeps
heavy models out of the web process:

- BGE-M3 document embeddings are built offline or in a separate worker.
- The web app reads v2 chunks from Supabase.
- Optional query embedding and reranking can be delegated to external APIs.
- If external model APIs are not configured, v2 falls back to lexical DB search
  and the existing lightweight reranking logic.

## Tables

The default v2 table is `maintenance_docs_chunks_v2`.

It stores the same chunk metadata as `maintenance_docs_chunks`, plus:

- `embedding_model`
- `embedding_dim`
- `embedding vector(1024)` for BGE-M3

## Build v2 Index

Install embedding dependencies on a local machine or worker:

```powershell
pip install -r backend\requirements.txt
pip install -r backend\requirements-embeddings.txt
```

Build BGE-M3 embeddings into Supabase:

```powershell
$env:SUPABASE_PROFILE="main"
$env:SUPABASE_PROFILE_STRICT="1"
python v2\build_bge_m3_index.py --force
```

For fresh:

```powershell
$env:SUPABASE_PROFILE="fresh"
$env:SUPABASE_PROFILE_STRICT="1"
python v2\build_bge_m3_index.py --force
```

## Use v2 Search

The existing API can be called with `version=v2`:

```text
GET /api/search?q=오므론에 대한 정보 알려줘&version=v2
```

For chat, include `version: "v2"` in the JSON payload.

## Optional External APIs

Render free should not load BGE-M3 or BGE reranker in-process. Configure these
only when a separate model service exists:

```env
RAG_V2_QUERY_EMBEDDING_URL=https://...
RAG_V2_RERANK_URL=https://...
```

Expected query embedding response:

```json
{"embedding": [0.01, 0.02]}
```

Expected rerank request:

```json
{"query": "...", "documents": [{"id": "chunk-id", "text": "..."}], "top_k": 5}
```

Expected rerank response:

```json
{"results": [{"id": "chunk-id", "score": 0.91}]}
```

