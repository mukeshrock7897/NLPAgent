import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

DB_PATH = os.getenv("NLPAGENT_DB_PATH", "data/nlpagent.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(cur: sqlite3.Cursor, table: str) -> List[str]:
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]

def _maybe_add_column(cur: sqlite3.Cursor, table: str, column_def: str) -> None:
    col_name = column_def.split()[0]
    cols = _table_columns(cur, table)
    if col_name in cols:
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")


def _migrate_pipeline_steps(cur: sqlite3.Cursor) -> None:
    cols = _table_columns(cur, "pipeline_steps")
    if not cols:
        return
    if "idx" in cols and "title" in cols:
        return

    cur.execute("ALTER TABLE pipeline_steps RENAME TO pipeline_steps_legacy")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, idx),
            FOREIGN KEY(session_id) REFERENCES chats(session_id)
        )
        """
    )

    rows = cur.execute(
        """
        SELECT session_id, tool_name, step_id, status, created_at, updated_at
        FROM pipeline_steps_legacy
        ORDER BY id ASC
        """
    ).fetchall()

    idx_map: Dict[str, int] = {}
    for r in rows:
        session_id = r[0]
        idx = idx_map.get(session_id, 0)
        idx_map[session_id] = idx + 1
        tool_name = r[1] or ""
        title = r[2] or tool_name or f"Step {idx + 1}"
        status = r[3] or "queued"
        created_at = r[4] or _now()
        updated_at = r[5] or created_at
        cur.execute(
            """
            INSERT OR IGNORE INTO pipeline_steps
            (session_id, idx, tool_name, title, status, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (session_id, idx, tool_name, title, status, created_at, updated_at),
        )


def init_db() -> None:
    conn = connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chats (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chats(session_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chats(session_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,             -- idle | running | blocked | completed | rejected | error
            current_step INTEGER NOT NULL,
            context_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chats(session_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,             -- queued | pending | running | completed | rejected | error
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_id, idx),
            FOREIGN KEY(session_id) REFERENCES chats(session_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    _maybe_add_column(cur, "chats", "user_id INTEGER")

    _migrate_pipeline_steps(cur)

    conn.commit()
    conn.close()


# ---------------- Chats ----------------

def upsert_chat(session_id: str, title: str, user_id: Optional[int] = None) -> None:
    conn = connect()
    cur = conn.cursor()
    now = _now()
    cur.execute(
        """
        INSERT INTO chats(session_id, user_id, title, created_at, updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET
          title=excluded.title,
          user_id=CASE WHEN chats.user_id IS NULL THEN excluded.user_id ELSE chats.user_id END,
          updated_at=excluded.updated_at
        """,
        (session_id, user_id, title, now, now),
    )
    conn.commit()
    conn.close()


def touch_chat(session_id: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE chats SET updated_at=? WHERE session_id=?", (_now(), session_id))
    conn.commit()
    conn.close()


def list_chats(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    if user_id is None:
        rows = cur.execute(
        """
        SELECT
            c.session_id,
            c.user_id,
            c.title,
            c.created_at,
            c.updated_at,
            (
                SELECT content
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message,
            (
                SELECT role
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_role,
            (
                SELECT created_at
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message_at
        FROM chats c
        ORDER BY c.updated_at DESC
        """
        ).fetchall()
    else:
        rows = cur.execute(
        """
        SELECT
            c.session_id,
            c.user_id,
            c.title,
            c.created_at,
            c.updated_at,
            (
                SELECT content
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message,
            (
                SELECT role
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_role,
            (
                SELECT created_at
                FROM messages m
                WHERE m.session_id = c.session_id
                ORDER BY m.id DESC
                LIMIT 1
            ) AS last_message_at
        FROM chats c
        WHERE c.user_id = ?
        ORDER BY c.updated_at DESC
        """,
        (user_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_chat_title(session_id: str, title: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE chats SET title=?, updated_at=? WHERE session_id=?",
        (title, _now(), session_id),
    )
    conn.commit()
    conn.close()


def get_chat(session_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    if user_id is None:
        row = cur.execute(
            "SELECT session_id, user_id, title, created_at, updated_at FROM chats WHERE session_id=?",
            (session_id,),
        ).fetchone()
    else:
        row = cur.execute(
            "SELECT session_id, user_id, title, created_at, updated_at FROM chats WHERE session_id=? AND user_id=?",
            (session_id, user_id),
        ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- Messages ----------------

def add_message(session_id: str, role: str, content: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES(?,?,?,?)",
        (session_id, role, content, _now()),
    )
    conn.commit()
    conn.close()
    touch_chat(session_id)


def list_messages(session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE session_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (session_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- Uploads ----------------

def add_upload(session_id: str, filename: str, path: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO uploads(session_id, filename, path, created_at) VALUES(?,?,?,?)",
        (session_id, filename, path, _now()),
    )
    conn.commit()
    conn.close()
    touch_chat(session_id)


def latest_upload(session_id: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT filename, path, created_at
        FROM uploads
        WHERE session_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- Pipeline ----------------

def create_pipeline_run(session_id: str, context_json: str) -> None:
    conn = connect()
    cur = conn.cursor()
    now = _now()
    cur.execute(
        """
        INSERT INTO pipeline_runs(session_id, status, current_step, context_json, created_at, updated_at)
        VALUES(?, 'blocked', 0, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          status='blocked',
          current_step=0,
          context_json=excluded.context_json,
          updated_at=excluded.updated_at
        """,
        (session_id, context_json, now, now),
    )
    conn.commit()
    conn.close()


def set_pipeline_status(session_id: str, status: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pipeline_runs SET status=?, updated_at=? WHERE session_id=?",
        (status, _now(), session_id),
    )
    conn.commit()
    conn.close()


def get_pipeline_run(session_id: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT session_id, status, current_step, context_json, created_at, updated_at FROM pipeline_runs WHERE session_id=?",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def set_pipeline_context(session_id: str, context_json: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pipeline_runs SET context_json=?, updated_at=? WHERE session_id=?",
        (context_json, _now(), session_id),
    )
    conn.commit()
    conn.close()


def set_current_step(session_id: str, idx: int) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE pipeline_runs SET current_step=?, updated_at=? WHERE session_id=?",
        (idx, _now(), session_id),
    )
    conn.commit()
    conn.close()


def upsert_step(session_id: str, idx: int, tool_name: str, title: str, status: str) -> None:
    conn = connect()
    cur = conn.cursor()
    now = _now()
    cur.execute(
        """
        INSERT INTO pipeline_steps(session_id, idx, tool_name, title, status, created_at, updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(session_id, idx) DO UPDATE SET
          tool_name=excluded.tool_name,
          title=excluded.title,
          status=excluded.status,
          updated_at=excluded.updated_at
        """,
        (session_id, idx, tool_name, title, status, now, now),
    )
    conn.commit()
    conn.close()


def list_steps(session_id: str) -> List[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT idx, tool_name, title, status, created_at, updated_at
        FROM pipeline_steps
        WHERE session_id=?
        ORDER BY idx ASC
        """,
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------- Users + Sessions ----------------

def create_user(username: str, email: str, password_hash: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    now = _now()
    try:
        cur.execute(
            """
            INSERT INTO users(username, email, password_hash, created_at, updated_at)
            VALUES(?,?,?,?,?)
            """,
            (username, email, password_hash, now, now),
        )
        user_id = cur.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return None
    conn.close()
    return {"id": user_id, "username": username, "email": email}


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        "SELECT id, username, email, password_hash, created_at, updated_at FROM users WHERE id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_identifier(identifier: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, username, email, password_hash, created_at, updated_at
        FROM users
        WHERE username=? OR email=?
        """,
        (identifier, identifier),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, username, email, password_hash, created_at, updated_at
        FROM users
        WHERE email=?
        """,
        (email,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_password(user_id: int, password_hash: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
        (password_hash, _now(), user_id),
    )
    conn.commit()
    conn.close()


def create_session(user_id: int, token: str, expires_at: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_sessions(session_token, user_id, created_at, expires_at)
        VALUES(?,?,?,?)
        """,
        (token, user_id, _now(), expires_at),
    )
    conn.commit()
    conn.close()


def get_session(token: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT session_token, user_id, created_at, expires_at
        FROM user_sessions
        WHERE session_token=?
        """,
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_sessions WHERE session_token=?", (token,))
    conn.commit()
    conn.close()


def create_password_reset(user_id: int, token: str, expires_at: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO password_resets(token, user_id, created_at, expires_at)
        VALUES(?,?,?,?)
        """,
        (token, user_id, _now(), expires_at),
    )
    conn.commit()
    conn.close()


def get_password_reset(token: str) -> Optional[Dict[str, Any]]:
    conn = connect()
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT id, token, user_id, created_at, expires_at, used_at
        FROM password_resets
        WHERE token=?
        """,
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_password_reset_used(token: str) -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute(
        "UPDATE password_resets SET used_at=? WHERE token=?",
        (_now(), token),
    )
    conn.commit()
    conn.close()
