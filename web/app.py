from dotenv import load_dotenv
load_dotenv()  # ✅ loads .env from project root (current working directory)

import os
import json
import asyncio
import traceback
import re
import secrets
import hashlib
import hmac
import binascii
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, UploadFile, File, Request, WebSocket, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from openai import OpenAI

from web import db
from web.state import (
    ensure_chat,
    get_openai_messages,
    pipeline_start,
    pipeline_next_pending,
    PIPELINE_TEMPLATE,
)

from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_SERVER_URL = os.getenv("NLPAGENT_MCP_URL", "http://127.0.0.1:8000/mcp")
WEB_TITLE = "NLPAGENT"

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
RAG_TOP_K = int(os.getenv("NLPAGENT_RAG_TOP_K", "8"))
RAG_MAX_CHARS = int(os.getenv("NLPAGENT_RAG_MAX_CHARS", "1200"))

# Auth
SESSION_COOKIE = "nlpagent_session"
SESSION_DAYS_DEFAULT = 1
SESSION_DAYS_REMEMBER = 30
RESET_TOKEN_HOURS = 2

# MCP
_mcp_client: Optional[MultiServerMCPClient] = None
_tool_map: Dict[str, Any] = {}  # name -> LangChain tool
_mcp_lock = asyncio.Lock()


def _load_tools_sync(tools: List[Any]) -> Dict[str, Any]:
    m: Dict[str, Any] = {}
    for t in tools:
        name = getattr(t, "name", None) or getattr(t, "__name__", None) or str(t)
        m[name] = t
    return m


async def mcp_connect_and_load(force: bool = False) -> None:
    """
    Connect to MCP and load tools.
    Robust: never throws to crash the UI server.
    """
    global _mcp_client, _tool_map

    async with _mcp_lock:
        if _tool_map and not force:
            return

        try:
            # ✅ FIX: server config must include transport + url
            _mcp_client = MultiServerMCPClient(
                {
                    "default": {
                        "transport": "http",
                        "url": MCP_SERVER_URL,
                    }
                },
                tool_name_prefix=False,
            )
            tools = await _mcp_client.get_tools()
            _tool_map = _load_tools_sync(tools)
            print(f"✅ MCP connected: {len(_tool_map)} tools loaded from {MCP_SERVER_URL}")
        except Exception as e:
            _mcp_client = None
            _tool_map = {}
            print(f"⚠️ MCP connect failed (UI will still run): {e}")


async def ensure_tools_loaded() -> None:
    if _tool_map:
        return
    await mcp_connect_and_load(force=True)


async def mcp_run_tool(tool_name: str, args: Dict[str, Any]) -> Any:
    await ensure_tools_loaded()

    if tool_name not in _tool_map:
        raise RuntimeError(f"Tool not found: {tool_name}. Tools loaded: {sorted(_tool_map.keys())}")

    tool = _tool_map[tool_name]

    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(args)

    return await anyio.to_thread.run_sync(tool.invoke, args)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    if not salt:
        salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return f"{salt}${binascii.hexlify(digest).decode('ascii')}"


def _verify_password(stored: str, password: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, hashed = stored.split("$", 1)
    candidate = _hash_password(password, salt=salt).split("$", 1)[1]
    return hmac.compare_digest(candidate, hashed)


def _create_session_response(user_id: int, remember: bool = False) -> JSONResponse:
    token = secrets.token_urlsafe(32)
    days = SESSION_DAYS_REMEMBER if remember else SESSION_DAYS_DEFAULT
    expires = _now_dt() + timedelta(days=days)
    db.create_session(user_id, token, _iso(expires))

    resp = JSONResponse({"ok": True, "redirect": "/app"})
    max_age = int((expires - _now_dt()).total_seconds())
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
    )
    return resp


def _get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = db.get_session(token)
    if not session:
        return None
    expires = _parse_iso(session.get("expires_at", ""))
    if expires and expires < _now_dt():
        db.delete_session(token)
        return None
    user = db.get_user_by_id(session["user_id"])
    if not user:
        db.delete_session(token)
        return None
    return user


def _require_user(request: Request) -> Dict[str, Any]:
    user = _get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _require_chat_access(user_id: int, session_id: str) -> None:
    if not session_id or not db.get_chat(session_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Chat not found")

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # ✅ do not crash if MCP not ready
    await mcp_connect_and_load(force=False)
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="web/static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------- Streamlit-compat endpoints (avoid spam) ----------------

@app.get("/_stcore/health")
async def stcore_health():
    return JSONResponse({"ok": True})

@app.get("/_stcore/host-config")
async def stcore_host_config():
    return JSONResponse({"ok": True})

@app.websocket("/_stcore/stream")
async def stcore_stream(ws: WebSocket):
    await ws.accept()
    await ws.close()


# ---------------- UI ----------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/app")
    with open("web/static/landing.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/reset", response_class=HTMLResponse)
async def reset_landing(request: Request):
    if _get_current_user(request):
        return RedirectResponse("/app")
    with open("web/static/landing.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/app", response_class=HTMLResponse)
async def app_home(request: Request):
    if not _get_current_user(request):
        return RedirectResponse("/")
    with open("web/static/index.html", "r", encoding="utf-8") as f:
        return f.read()


# ---------------- API: system status ----------------

@app.get("/api/health")
async def api_health():
    if not _tool_map:
        await mcp_connect_and_load(force=False)

    return {
        "app": WEB_TITLE,
        "mcp_url": MCP_SERVER_URL,
        "tools_loaded": len(_tool_map),
        "mcp_connected": bool(_tool_map),
        "openai_configured": bool(OPENAI_API_KEY),
        "model": OPENAI_MODEL,
    }


# ---------------- API: auth ----------------

@app.get("/api/auth/session")
async def api_auth_session(request: Request):
    user = _get_current_user(request)
    if not user:
        return {"ok": False}
    return {"ok": True, "user": {"id": user["id"], "username": user["username"], "email": user["email"]}}


@app.post("/api/auth/signup")
async def api_auth_signup(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    remember = bool(body.get("remember"))

    if len(username) < 3 or len(email) < 5 or "@" not in email:
        return JSONResponse({"ok": False, "error": "Enter a valid username and email."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"ok": False, "error": "Password must be at least 6 characters."}, status_code=400)

    password_hash = _hash_password(password)
    user = db.create_user(username, email, password_hash)
    if not user:
        return JSONResponse({"ok": False, "error": "Username or email already exists."}, status_code=400)

    return _create_session_response(user["id"], remember=remember)


@app.post("/api/auth/login")
async def api_auth_login(request: Request):
    body = await request.json()
    identifier = (body.get("identifier") or body.get("username") or body.get("email") or "").strip()
    password = body.get("password") or ""
    remember = bool(body.get("remember"))

    if not identifier or not password:
        return JSONResponse({"ok": False, "error": "Enter your username/email and password."}, status_code=400)

    lookup = identifier.lower() if "@" in identifier else identifier
    user = db.get_user_by_identifier(lookup)
    if not user or not _verify_password(user.get("password_hash", ""), password):
        return JSONResponse({"ok": False, "error": "Invalid credentials."}, status_code=401)

    return _create_session_response(user["id"], remember=remember)


@app.post("/api/auth/logout")
async def api_auth_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        db.delete_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.post("/api/auth/forgot")
async def api_auth_forgot(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    if not email:
        return JSONResponse({"ok": False, "error": "Enter your email address."}, status_code=400)

    user = db.get_user_by_email(email)
    if user:
        token = secrets.token_urlsafe(24)
        expires = _now_dt() + timedelta(hours=RESET_TOKEN_HOURS)
        db.create_password_reset(user["id"], token, _iso(expires))
        return {"ok": True, "reset_url": f"/reset?token={token}"}

    return {"ok": True}


@app.post("/api/auth/reset")
async def api_auth_reset(request: Request):
    body = await request.json()
    token = (body.get("token") or "").strip()
    password = body.get("password") or ""
    if not token or len(password) < 6:
        return JSONResponse({"ok": False, "error": "Invalid token or password."}, status_code=400)

    reset = db.get_password_reset(token)
    if not reset or reset.get("used_at"):
        return JSONResponse({"ok": False, "error": "Reset link is invalid or already used."}, status_code=400)

    expires = _parse_iso(reset.get("expires_at", ""))
    if expires and expires < _now_dt():
        return JSONResponse({"ok": False, "error": "Reset link has expired."}, status_code=400)

    db.update_user_password(reset["user_id"], _hash_password(password))
    db.mark_password_reset_used(token)
    return {"ok": True}


# ---------------- API: chat sessions ----------------

@app.get("/api/chats")
async def api_chats(request: Request):
    user = _require_user(request)
    return {"chats": db.list_chats(user_id=user["id"])}

@app.post("/api/chats/new")
async def api_chats_new(request: Request):
    user = _require_user(request)
    body = await request.json()
    session_id = body.get("session_id")
    title = body.get("title") or "New Chat"
    if not session_id:
        return JSONResponse({"ok": False, "error": "Missing session_id"}, status_code=400)
    existing = db.get_chat(session_id)
    if existing and existing.get("user_id") and existing["user_id"] != user["id"]:
        return JSONResponse({"ok": False, "error": "Session already exists."}, status_code=409)
    ensure_chat(session_id, title=title, user_id=user["id"])
    return {"ok": True}

@app.get("/api/chats/{session_id}")
async def api_chat_get(session_id: str, request: Request):
    user = _require_user(request)
    _require_chat_access(user["id"], session_id)
    pipeline = db.get_pipeline_run(session_id)
    latest = db.latest_upload(session_id)
    pipeline_stale = False
    if pipeline and latest:
        try:
            ctx = json.loads(pipeline.get("context_json") or "{}")
            if ctx.get("pdf_path") and latest.get("path") and ctx.get("pdf_path") != latest.get("path"):
                pipeline_stale = True
        except Exception:
            pipeline_stale = False
    return {
        "chat": db.get_chat(session_id, user_id=user["id"]),
        "messages": db.list_messages(session_id, limit=500),
        "steps": db.list_steps(session_id),
        "pipeline": pipeline,
        "pipeline_stale": pipeline_stale,
        "latest_upload": latest,
    }


# ---------------- API: upload ----------------

@app.post("/api/upload")
async def api_upload(session_id: str, request: Request, file: UploadFile = File(...)):
    user = _require_user(request)
    _require_chat_access(user["id"], session_id)
    os.makedirs("data/uploads", exist_ok=True)
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    path = os.path.join("data/uploads", safe_name)

    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)

    db.add_upload(session_id, safe_name, path)
    _maybe_update_title(session_id, _title_from_filename(safe_name))
    return {"ok": True, "path": path, "filename": safe_name}


# ---------------- OpenAI streaming ----------------

def _system_prompt() -> str:
    return (
        "You are NLPAGENT, a precise document assistant.\n"
        "If document context is provided, answer ONLY from that context. Do not add assumptions.\n"
        "When asked to list items (e.g., projects, skills), list every item found in the document context.\n"
        "Use markdown with clear headings and bullet lists. Put each item on its own line.\n"
        "Keep the response short, clear, and easy to read. Prefer bullets.\n"
        "If the answer is not in the document, reply exactly: \"Not found in document.\"\n"
        "Do not mention pipelines, tools, or internal limitations when context exists.\n"
        "Never ask to upload a PDF when document context is provided.\n"
        "If no document context is provided, respond: \"Please upload a PDF and click Run pipeline, then ask again.\"\n"
    )


def _title_from_text(text: str, max_len: int = 56) -> str:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return ""
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3].rstrip() + "..."
    return cleaned


def _title_from_filename(filename: str, max_len: int = 56) -> str:
    base = os.path.basename(filename or "")
    name = os.path.splitext(base)[0]
    name = name.replace("_", " ").replace("-", " ").strip()
    return _title_from_text(name, max_len=max_len)


def _maybe_update_title(session_id: str, title: str) -> None:
    if not title:
        return
    chat = db.get_chat(session_id)
    if not chat:
        return
    current = (chat.get("title") or "").strip().lower()
    if current in {"new chat", "chat", ""}:
        db.update_chat_title(session_id, title)


def _latest_user_message(msgs: List[Dict[str, str]]) -> str:
    for msg in reversed(msgs):
        if msg.get("role") == "user" and msg.get("content"):
            return msg["content"].strip()
    return ""


def _format_rag_snippets(results: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for i, item in enumerate(results, start=1):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if len(text) > RAG_MAX_CHARS:
            text = text[:RAG_MAX_CHARS].rstrip() + "..."
        meta = item.get("metadata") or {}
        source = meta.get("source") or meta.get("file") or meta.get("path") or ""
        if source:
            lines.append(f"[{i}] {text}\nSource: {source}")
        else:
            lines.append(f"[{i}] {text}")
    return "\n\n".join(lines)


def _keyword_snippets(raw_text: str, query: str, doc_label: str) -> List[Dict[str, Any]]:
    text = raw_text or ""
    if not text.strip():
        return []
    tokens = re.findall(r"[a-zA-Z0-9]{3,}", (query or "").lower())
    stop = {"the", "and", "this", "that", "with", "from", "please", "about", "what", "list", "tell", "show"}
    terms = [t for t in tokens if t not in stop]
    if not terms:
        return []

    lines = [ln.strip() for ln in text.splitlines()]
    results: List[Dict[str, Any]] = []
    seen = set()
    for i, line in enumerate(lines):
        if not line:
            continue
        lower = line.lower()
        if not any(t in lower for t in terms):
            continue
        window = []
        for j in range(max(0, i - 1), min(len(lines), i + 2)):
            if lines[j]:
                window.append(lines[j])
        snippet = " ".join(window).strip()
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        results.append({"text": snippet, "metadata": {"source": doc_label or "document"}})
        if len(results) >= RAG_TOP_K:
            break
    return results


def _fallback_results_from_context(ctx: Dict[str, Any], doc_label: str, query: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    raw_text = ctx.get("raw_text") or ""

    if isinstance(raw_text, str) and raw_text.strip():
        results = _keyword_snippets(raw_text, query, doc_label)

    if not results:
        chunks = ctx.get("chunks")
        if isinstance(chunks, list):
            for item in chunks:
                text = ""
                if isinstance(item, str):
                    text = item
                elif isinstance(item, dict):
                    text = str(item.get("text") or "")
                if not text.strip():
                    continue
                results.append({"text": text, "metadata": {"source": doc_label or "document"}})
                if len(results) >= RAG_TOP_K:
                    break

    if not results:
        base_text = ctx.get("clean_text") or raw_text
        if isinstance(base_text, str) and base_text.strip():
            results.append({"text": base_text, "metadata": {"source": doc_label or "document"}})

    return results


async def _maybe_get_rag_context(session_id: str, msgs: List[Dict[str, str]]) -> Optional[str]:
    run = db.get_pipeline_run(session_id)
    if not run or run.get("status") != "completed":
        return None

    query = _latest_user_message(msgs)
    if not query:
        return None

    try:
        ctx = json.loads(run.get("context_json") or "{}")
    except Exception:
        return None

    latest = db.latest_upload(session_id)
    if latest and ctx.get("pdf_path") and latest.get("path") and ctx.get("pdf_path") != latest.get("path"):
        return None

    index_name = ctx.get("index_name") or "nlpagent-default"
    doc_label = ""
    pdf_path = ctx.get("pdf_path") or ""
    if isinstance(pdf_path, str) and pdf_path:
        doc_label = os.path.basename(pdf_path)
    result = None
    try:
        result = await mcp_run_tool(
            "vector_query_tool",
            {"query": query, "index_name": index_name, "top_k": RAG_TOP_K},
        )
    except Exception as e:
        print(f"⚠️ RAG query failed: {e}. Falling back to stored context.")

    results: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        results = result.get("results") or []

    if not results:
        results = _fallback_results_from_context(ctx, doc_label, query)

    if not results and ctx.get("pdf_path") and not ctx.get("raw_text"):
        try:
            raw = await mcp_run_tool("read_pdf_local_tool", {"path": ctx["pdf_path"]})
            if isinstance(raw, str) and raw.strip():
                ctx["raw_text"] = raw
                db.set_pipeline_context(session_id, json.dumps(ctx))
                results = _fallback_results_from_context(ctx, doc_label, query)
        except Exception as e:
            print(f"⚠️ PDF fallback failed: {e}")
    if not results:
        return None

    snippets = _format_rag_snippets(results)
    if not snippets:
        return None

    header = "RAG context from the indexed document."
    if doc_label:
        header = f"RAG context from {doc_label}."

    return (
        f"{header} This is the only source. Answer strictly from it. "
        "If the answer is missing, reply: \"Not found in document.\"\n\n"
        f"{snippets}"
    )


async def stream_openai_response(session_id: str) -> AsyncGenerator[bytes, None]:
    if not OPENAI_API_KEY:
        yield b"data: [ERROR] Missing OPENAI_API_KEY in environment.\n\n"
        yield b"data: [DONE]\n\n"
        return

    client = OpenAI(api_key=OPENAI_API_KEY)

    history = get_openai_messages(session_id, limit=30)
    msgs = [{"role": "system", "content": _system_prompt()}]
    rag_context = await _maybe_get_rag_context(session_id, history)
    if rag_context:
        msgs.append({"role": "system", "content": rag_context})
    msgs.extend(history)

    try:
        stream = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=msgs,
            stream=True,
            temperature=0.2,
        )
        full = []
        for ev in stream:
            delta = ""
            if ev.choices and ev.choices[0].delta and ev.choices[0].delta.content:
                delta = ev.choices[0].delta.content
            if delta:
                full.append(delta)
                yield f"data: {delta}\n\n".encode("utf-8")
        final_text = "".join(full).strip()
        if final_text:
            db.add_message(session_id, "assistant", final_text)
        yield b"data: [DONE]\n\n"
    except Exception as e:
        yield f"data: [ERROR] {str(e)}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"


# ---------------- API: chat ----------------

@app.post("/api/chat")
async def api_chat(request: Request):
    user = _require_user(request)
    body = await request.json()
    session_id = body.get("session_id")
    text = (body.get("message") or "").strip()

    if not session_id:
        return JSONResponse({"ok": False, "error": "Missing session_id"}, status_code=400)
    _require_chat_access(user["id"], session_id)

    if not text:
        return JSONResponse({"ok": False, "error": "Empty message"}, status_code=400)

    db.add_message(session_id, "user", text)
    lower = text.lower()
    if "run the pipeline" not in lower and "run pipeline" not in lower:
        _maybe_update_title(session_id, _title_from_text(text))

    latest = db.latest_upload(session_id)
    if latest and "run the pipeline" in text.lower():
        first = pipeline_start(session_id, latest["path"], user_id=user["id"])
        return {
            "mode": "pipeline",
            "first_step": first,
            "steps": db.list_steps(session_id),
        }

    return {"mode": "chat", "ok": True}


@app.get("/api/chat/stream")
async def api_chat_stream(session_id: str, request: Request):
    user = _require_user(request)
    _require_chat_access(user["id"], session_id)
    return StreamingResponse(stream_openai_response(session_id), media_type="text/event-stream")


# ---------------- API: pipeline decisions ----------------

@app.post("/api/pipeline/decision")
async def api_pipeline_decision(request: Request):
    user = _require_user(request)
    body = await request.json()
    session_id = body.get("session_id")
    decision = body.get("decision")  # approve | reject

    _require_chat_access(user["id"], session_id)

    run = db.get_pipeline_run(session_id)
    if not run:
        return JSONResponse({"ok": False, "error": "No pipeline for this chat."}, status_code=400)

    steps = db.list_steps(session_id)
    current_idx = run["current_step"]

    if current_idx >= len(steps):
        db.set_pipeline_status(session_id, "completed")
        return {"ok": True, "status": "completed", "steps": steps}

    current = steps[current_idx]
    if current["status"] not in ("pending", "running"):
        pending = pipeline_next_pending(session_id)
        return {"ok": True, "status": "blocked", "steps": steps, "pending": pending}

    if decision == "reject":
        db.upsert_step(session_id, current_idx, current["tool_name"], current["title"], "rejected")
        db.set_pipeline_status(session_id, "rejected")
        return {"ok": True, "status": "rejected", "steps": db.list_steps(session_id)}

    try:
        db.set_pipeline_status(session_id, "running")
        db.upsert_step(session_id, current_idx, current["tool_name"], current["title"], "running")

        ctx = json.loads(run["context_json"])
        tool_name = current["tool_name"]
        args: Dict[str, Any] = {}

        if tool_name == "read_pdf_local_tool":
            args = {"path": ctx["pdf_path"]}
            out = await mcp_run_tool(tool_name, args)
            if not isinstance(out, str) or not out.strip():
                raise ValueError("No text extracted from the PDF.")
            ctx["raw_text"] = out

        elif tool_name == "clean_text_tool":
            args = {"text": ctx["raw_text"] or ""}
            out = await mcp_run_tool(tool_name, args)
            if not isinstance(out, str) or not out.strip():
                ctx["clean_text"] = ctx.get("raw_text") or ""
            else:
                ctx["clean_text"] = out

        elif tool_name == "semantic_chunker_tool":
            source_text = ctx.get("raw_text") or ctx.get("clean_text") or ""
            args = {"text": source_text, "strategy": "recursive", "max_chars": 1400, "overlap": 160}
            out = await mcp_run_tool(tool_name, args)
            if not isinstance(out, list) or not out:
                raise ValueError("No chunks created from the document.")
            ctx["chunks"] = out

        elif tool_name == "embed_texts_tool":
            chunks = ctx["chunks"] or []
            texts = []
            for c in chunks:
                if isinstance(c, str):
                    texts.append(c)
                elif isinstance(c, dict) and "text" in c:
                    texts.append(c["text"])
            args = {"texts": texts}
            out = await mcp_run_tool(tool_name, args)
            if not isinstance(out, list) or not out:
                raise ValueError("No embeddings created.")
            ctx["embeddings"] = out

        elif tool_name == "vector_upsert_tool":
            args = {
                "index_name": ctx.get("index_name", "nlpagent-default"),
                "chunks": ctx.get("chunks", []),
                "embeddings": ctx.get("embeddings", None),
            }
            out = await mcp_run_tool(tool_name, args)
            if isinstance(out, dict) and int(out.get("upserted", 0)) == 0:
                raise ValueError("No chunks were upserted into the vector index.")

        db.set_pipeline_context(session_id, json.dumps(ctx))
        db.upsert_step(session_id, current_idx, tool_name, current["title"], "completed")

        next_idx = current_idx + 1
        db.set_current_step(session_id, next_idx)

        if next_idx < len(PIPELINE_TEMPLATE):
            nxt = db.list_steps(session_id)[next_idx]
            db.upsert_step(session_id, next_idx, nxt["tool_name"], nxt["title"], "pending")
            db.set_pipeline_status(session_id, "blocked")
            return {
                "ok": True,
                "status": "blocked",
                "steps": db.list_steps(session_id),
                "pending": db.list_steps(session_id)[next_idx],
            }

        db.set_pipeline_status(session_id, "completed")
        return {"ok": True, "status": "completed", "steps": db.list_steps(session_id)}

    except Exception as e:
        print(traceback.format_exc())
        db.upsert_step(session_id, current_idx, current["tool_name"], current["title"], "error")
        db.set_pipeline_status(session_id, "error")
        return JSONResponse(
            {"ok": False, "status": "error", "error": str(e), "steps": db.list_steps(session_id)},
            status_code=500,
        )
