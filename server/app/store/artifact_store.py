from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB_PATH = Path(".artifact_store.sqlite3")

def _now() -> int:
    return int(time.time())

def _connect(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    con = _connect(db_path)
    try:
        con.execute(
            """CREATE TABLE IF NOT EXISTS texts(
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER NOT NULL
            );"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS chunks(
                id TEXT PRIMARY KEY,
                chunks_json TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER NOT NULL
            );"""
        )
        con.commit()
    finally:
        con.close()

def put_text(text: str, metadata: Optional[Dict[str, Any]] = None, db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    init_db(db_path)
    aid = str(uuid.uuid4())
    con = _connect(db_path)
    try:
        con.execute(
            "INSERT INTO texts(id, text, metadata, created_at) VALUES(?,?,?,?)",
            (aid, text or "", json.dumps(metadata or {}), _now()),
        )
        con.commit()
    finally:
        con.close()
    return {"artifact_id": aid, "chars": len(text or ""), "metadata": metadata or {}}

def get_text(artifact_id: str, db_path: Path = DEFAULT_DB_PATH) -> str:
    init_db(db_path)
    con = _connect(db_path)
    try:
        cur = con.execute("SELECT text FROM texts WHERE id=?", (artifact_id,))
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Unknown text artifact_id: {artifact_id}")
        return row[0]
    finally:
        con.close()

def preview_text(artifact_id: str, max_chars: int = 800, db_path: Path = DEFAULT_DB_PATH) -> str:
    t = get_text(artifact_id, db_path=db_path).replace("\r\n", "\n")
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n... [TRUNCATED]"

def put_chunks(chunks: List[str], metadata: Optional[Dict[str, Any]] = None, db_path: Path = DEFAULT_DB_PATH) -> Dict[str, Any]:
    init_db(db_path)
    cid = str(uuid.uuid4())
    con = _connect(db_path)
    try:
        con.execute(
            "INSERT INTO chunks(id, chunks_json, metadata, created_at) VALUES(?,?,?,?)",
            (cid, json.dumps(chunks or []), json.dumps(metadata or {}), _now()),
        )
        con.commit()
    finally:
        con.close()
    return {"chunks_id": cid, "n": len(chunks or []), "metadata": metadata or {}}

def get_chunks(chunks_id: str, db_path: Path = DEFAULT_DB_PATH) -> List[str]:
    init_db(db_path)
    con = _connect(db_path)
    try:
        cur = con.execute("SELECT chunks_json FROM chunks WHERE id=?", (chunks_id,))
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Unknown chunks_id: {chunks_id}")
        return json.loads(row[0])
    finally:
        con.close()

def preview_chunks(chunks_id: str, limit: int = 3, db_path: Path = DEFAULT_DB_PATH) -> List[str]:
    chunks = get_chunks(chunks_id, db_path=db_path)
    return chunks[: max(0, int(limit))]
