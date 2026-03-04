#!/usr/bin/env python3
"""
Recall Semantic Search — Embedding-based session search engine.

Stores session summaries + embeddings in SQLite for fast semantic search.
Supports OpenAI text-embedding-3-small API with keyword search fallback.

Usage:
  python recall_search.py index <base_dir>                   # Index all sessions
  python recall_search.py index-one <base_dir> <session_id>  # Index a single session
  python recall_search.py search <base_dir> <query> [--top-k 5]  # Semantic search
  python recall_search.py keyword <base_dir> <query>         # Keyword fallback search
"""

import argparse
import json
import math
import os
import platform
import re
import sqlite3
import struct
import sys
import urllib.request
import urllib.parse
from pathlib import Path

# Fix Windows terminal encoding
if platform.system() == "Windows" or "MSYS" in os.environ.get("MSYSTEM", ""):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE_PATH = r"D:\claude-sessions"
DB_NAME = "_index.sqlite"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536


def _normalize_path(path_str: str) -> str:
    """Convert MSYS-style paths to Windows paths if needed."""
    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
        drive_letter = path_str[1].upper()
        return f"{drive_letter}:{path_str[2:]}".replace("/", "\\")
    return path_str


def _safe_load_json(file_path) -> dict:
    """Load JSON file with fallback to fix unescaped Windows backslashes."""
    with open(file_path, "r", encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        fixed = re.sub(r'(?<!\\)\\(?![\\"/bfnrtu])', r'\\\\', raw)
        return json.loads(fixed)


def _get_db_path(base_path: Path) -> Path:
    return base_path / DB_NAME


def _init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the SQLite database with the required schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            abstract TEXT,
            tags TEXT,
            first_prompt TEXT,
            embedding BLOB,
            embedding_model TEXT,
            indexed_at TEXT,
            meta_path TEXT
        )
    """)
    conn.commit()
    return conn


def _get_openai_key() -> str:
    """Get OpenAI API key from environment or config."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key

    # Try to read from central config
    base_path = Path(_normalize_path(DEFAULT_BASE_PATH))
    config_path = base_path / "_config.json"
    if config_path.exists():
        try:
            config = _safe_load_json(config_path)
            key = config.get("openai_api_key", "")
            if key:
                return key
        except Exception:
            pass

    return ""


def _get_embedding_openai(text: str, api_key: str) -> list:
    """Get embedding vector from OpenAI API.

    Args:
        text: Text to embed (will be truncated to ~8000 chars)
        api_key: OpenAI API key

    Returns:
        List of floats (embedding vector) or empty list on failure
    """
    if not api_key:
        return []

    # Truncate to avoid token limits
    text = text[:8000]

    url = "https://api.openai.com/v1/embeddings"
    data = json.dumps({
        "input": text,
        "model": EMBEDDING_MODEL
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["data"][0]["embedding"]
    except Exception as e:
        print(f"[recall search] embedding API error: {e}", file=sys.stderr)
        return []


def _embedding_to_blob(embedding: list) -> bytes:
    """Pack a float list into a compact binary blob."""
    return struct.pack(f'{len(embedding)}f', *embedding)


def _blob_to_embedding(blob: bytes) -> list:
    """Unpack a binary blob back to float list."""
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))


def _cosine_similarity(a: list, b: list) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _load_all_sessions(base_path: Path) -> list:
    """Load all session metadata from the central directory."""
    config_path = base_path / "_config.json"
    if not config_path.exists():
        return []
    try:
        config = _safe_load_json(config_path)
    except Exception:
        return []

    sessions = []
    for cat in config.get("categories", []):
        cat_dir = base_path / cat
        if not cat_dir.exists():
            continue
        for meta_file in cat_dir.glob("*_meta.json"):
            try:
                meta = _safe_load_json(meta_file)
                meta["_meta_path"] = str(meta_file)
                sessions.append(meta)
            except Exception:
                continue
    return sessions


def _build_search_text(meta: dict) -> str:
    """Build the text to embed for a session from its metadata."""
    parts = []
    if meta.get("name"):
        parts.append(f"会话名称: {meta['name']}")
    if meta.get("abstract"):
        parts.append(f"摘要: {meta['abstract']}")
    if meta.get("firstPrompt"):
        parts.append(f"首条消息: {meta['firstPrompt'][:200]}")
    if meta.get("tags"):
        parts.append(f"标签: {', '.join(meta['tags'])}")
    if meta.get("category"):
        parts.append(f"类别: {meta['category']}")
    return "\n".join(parts)


def index_all(base_dir: str) -> str:
    """Index all sessions in the central directory."""
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    db_path = _get_db_path(base_path)
    conn = _init_db(db_path)
    api_key = _get_openai_key()

    sessions = _load_all_sessions(base_path)
    if not sessions:
        conn.close()
        return "No sessions found to index."

    indexed = 0
    skipped = 0
    failed = 0

    for meta in sessions:
        session_id = meta.get("sessionId", "")
        if not session_id:
            skipped += 1
            continue

        search_text = _build_search_text(meta)
        if not search_text:
            skipped += 1
            continue

        # Get embedding
        embedding = _get_embedding_openai(search_text, api_key) if api_key else []
        embedding_blob = _embedding_to_blob(embedding) if embedding else None

        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()

            conn.execute("""
                INSERT OR REPLACE INTO sessions
                (session_id, name, category, abstract, tags, first_prompt,
                 embedding, embedding_model, indexed_at, meta_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                meta.get("name", ""),
                meta.get("category", ""),
                meta.get("abstract", ""),
                json.dumps(meta.get("tags", []), ensure_ascii=False),
                meta.get("firstPrompt", ""),
                embedding_blob,
                EMBEDDING_MODEL if embedding else None,
                now,
                meta.get("_meta_path", "")
            ))
            indexed += 1
        except Exception as e:
            print(f"[index] error indexing {session_id}: {e}", file=sys.stderr)
            failed += 1

    conn.commit()
    conn.close()

    lines = [
        f"索引完成: {indexed} 个会话已索引",
        f"跳过: {skipped}, 失败: {failed}",
        f"Embedding: {'OpenAI ({})'.format(EMBEDDING_MODEL) if api_key else '未配置 (仅关键词搜索)'}",
        f"数据库: {db_path}"
    ]
    return "\n".join(lines)


def index_one(base_dir: str, session_id: str) -> str:
    """Index or update a single session by sessionId."""
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    db_path = _get_db_path(base_path)
    conn = _init_db(db_path)
    api_key = _get_openai_key()

    sessions = _load_all_sessions(base_path)
    target = None
    for s in sessions:
        if s.get("sessionId") == session_id:
            target = s
            break

    if not target:
        conn.close()
        return f"Session not found: {session_id}"

    search_text = _build_search_text(target)
    embedding = _get_embedding_openai(search_text, api_key) if api_key else []
    embedding_blob = _embedding_to_blob(embedding) if embedding else None

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    conn.execute("""
        INSERT OR REPLACE INTO sessions
        (session_id, name, category, summary, tags, first_prompt,
         embedding, embedding_model, indexed_at, meta_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id,
        target.get("name", ""),
        target.get("category", ""),
        target.get("summary", ""),
        json.dumps(target.get("tags", []), ensure_ascii=False),
        target.get("firstPrompt", ""),
        embedding_blob,
        EMBEDDING_MODEL if embedding else None,
        now,
        target.get("_meta_path", "")
    ))

    conn.commit()
    conn.close()
    return f"已索引: {target.get('name', session_id)}"


def semantic_search(base_dir: str, query: str, top_k: int = 5) -> str:
    """Search sessions using embedding-based semantic similarity.

    Falls back to keyword search if no embeddings are available.
    """
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    db_path = _get_db_path(base_path)
    if not db_path.exists():
        return "搜索索引不存在。请先运行 `/recall search` 触发索引构建。"

    conn = _init_db(db_path)
    api_key = _get_openai_key()

    # Check if we have embeddings
    row = conn.execute("SELECT COUNT(*) FROM sessions WHERE embedding IS NOT NULL").fetchone()
    has_embeddings = row[0] > 0 if row else False

    if has_embeddings and api_key:
        # Semantic search path
        query_embedding = _get_embedding_openai(query, api_key)
        if not query_embedding:
            conn.close()
            return keyword_search(base_dir, query)

        # Load all sessions with embeddings
        rows = conn.execute("""
            SELECT session_id, name, category, abstract, tags, first_prompt, embedding, meta_path
            FROM sessions WHERE embedding IS NOT NULL
        """).fetchall()

        results = []
        for row in rows:
            sid, name, category, abstract, tags, fp, emb_blob, meta_path = row
            emb = _blob_to_embedding(emb_blob)
            sim = _cosine_similarity(query_embedding, emb)
            results.append({
                "session_id": sid,
                "name": name,
                "category": category,
                "abstract": abstract,
                "tags": tags,
                "first_prompt": fp,
                "similarity": sim,
                "meta_path": meta_path
            })

        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        results = results[:top_k]

        conn.close()

        if not results:
            return f"未找到与 '{query}' 相关的会话。"

        lines = [f"语义搜索 '{query}' — 找到 {len(results)} 个相关会话:", ""]
        lines.append(f"{'#':<4} {'相似度':<8} {'名称':<25} {'类别':<8} {'摘要预览':<40}")
        lines.append("-" * 90)

        for i, r in enumerate(results, 1):
            sim_str = f"{r['similarity']:.3f}"
            name = r["name"][:24] if r["name"] else "unnamed"
            cat = r["category"] or "?"
            summary_preview = (r["abstract"] or r["first_prompt"] or "")[:38]
            if len(summary_preview) == 38:
                summary_preview += ".."
            lines.append(f"{i:<4} {sim_str:<8} {name:<25} {cat:<8} {summary_preview:<40}")

        # Output JSON for machine-readable access
        lines.append("")
        lines.append("--- JSON ---")
        json_results = [{"session_id": r["session_id"], "name": r["name"],
                         "category": r["category"], "abstract": r["abstract"],
                         "similarity": round(r["similarity"], 4),
                         "meta_path": r["meta_path"]} for r in results]
        lines.append(json.dumps(json_results, ensure_ascii=False))

        return "\n".join(lines)
    else:
        conn.close()
        return keyword_search(base_dir, query)


def keyword_search(base_dir: str, query: str) -> str:
    """Fallback keyword search using SQLite full-text matching."""
    base_path = Path(_normalize_path(base_dir))
    if not base_path.exists():
        return f"Error: Directory not found: {base_dir}"

    db_path = _get_db_path(base_path)
    if not db_path.exists():
        # Fall back to direct meta file scanning
        return _keyword_search_filesystem(base_path, query)

    conn = _init_db(db_path)
    query_lower = query.lower()

    rows = conn.execute("""
        SELECT session_id, name, category, abstract, tags, first_prompt, meta_path
        FROM sessions
    """).fetchall()
    conn.close()

    results = []
    for row in rows:
        sid, name, category, abstract, tags, fp, meta_path = row
        searchable = " ".join([
            name or "", abstract or "", tags or "", fp or "", category or ""
        ]).lower()

        # Calculate keyword relevance score
        score = 0
        for word in query_lower.split():
            if word in searchable:
                score += searchable.count(word)
                if word in (name or "").lower():
                    score += 3  # Name match bonus
                if word in (tags or "").lower():
                    score += 2  # Tag match bonus

        if score > 0:
            results.append({
                "session_id": sid,
                "name": name,
                "category": category,
                "abstract": abstract,
                "score": score,
                "meta_path": meta_path
            })

    results.sort(key=lambda x: x["score"], reverse=True)

    if not results:
        return f"关键词搜索 '{query}' — 未找到匹配的会话。"

    lines = [f"关键词搜索 '{query}' — 找到 {len(results)} 个匹配:", ""]
    lines.append(f"{'#':<4} {'相关度':<8} {'名称':<25} {'类别':<8} {'摘要预览':<40}")
    lines.append("-" * 90)

    for i, r in enumerate(results[:10], 1):
        score_str = str(r["score"])
        name = r["name"][:24] if r["name"] else "unnamed"
        cat = r["category"] or "?"
        summary_preview = (r["summary"] or "")[:38]
        if len(summary_preview) == 38:
            summary_preview += ".."
        lines.append(f"{i:<4} {score_str:<8} {name:<25} {cat:<8} {summary_preview:<40}")

    # JSON output
    lines.append("")
    lines.append("--- JSON ---")
    json_results = [{"session_id": r["session_id"], "name": r["name"],
                     "category": r["category"], "abstract": r["abstract"],
                     "score": r["score"],
                     "meta_path": r["meta_path"]} for r in results[:10]]
    lines.append(json.dumps(json_results, ensure_ascii=False))

    return "\n".join(lines)


def _keyword_search_filesystem(base_path: Path, query: str) -> str:
    """Keyword search by directly scanning _meta.json files (no SQLite)."""
    sessions = _load_all_sessions(base_path)
    if not sessions:
        return "No sessions saved yet."

    query_lower = query.lower()
    matches = []

    for s in sessions:
        searchable = " ".join([
            s.get("name", ""), s.get("abstract", ""),
            s.get("firstPrompt", ""), " ".join(s.get("tags", [])),
            s.get("category", "")
        ]).lower()

        score = 0
        for word in query_lower.split():
            if word in searchable:
                score += searchable.count(word)

        if score > 0:
            matches.append((score, s))

    matches.sort(key=lambda x: x[0], reverse=True)

    if not matches:
        return f"关键词搜索 '{query}' — 未找到匹配。"

    lines = [f"关键词搜索 '{query}' — 找到 {len(matches)} 个匹配:", ""]
    for i, (score, s) in enumerate(matches[:10], 1):
        name = s.get("name", "unnamed")[:24]
        cat = s.get("category", "?")
        lines.append(f"  {i}. [{cat}] {name} (相关度: {score})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Recall Semantic Search Engine")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # index subcommand
    idx_parser = subparsers.add_parser("index", help="Index all sessions")
    idx_parser.add_argument("base_dir", help="Path to central sessions directory")

    # index-one subcommand
    idx1_parser = subparsers.add_parser("index-one", help="Index a single session")
    idx1_parser.add_argument("base_dir", help="Path to central sessions directory")
    idx1_parser.add_argument("session_id", help="Session ID to index")

    # search subcommand
    search_parser = subparsers.add_parser("search", help="Semantic search")
    search_parser.add_argument("base_dir", help="Path to central sessions directory")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--top-k", type=int, default=5, help="Number of results")

    # keyword subcommand
    kw_parser = subparsers.add_parser("keyword", help="Keyword search (fallback)")
    kw_parser.add_argument("base_dir", help="Path to central sessions directory")
    kw_parser.add_argument("query", help="Search query")

    args = parser.parse_args()

    if args.command == "index":
        print(index_all(args.base_dir))
    elif args.command == "index-one":
        print(index_one(args.base_dir, args.session_id))
    elif args.command == "search":
        print(semantic_search(args.base_dir, args.query, args.top_k))
    elif args.command == "keyword":
        print(keyword_search(args.base_dir, args.query))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
