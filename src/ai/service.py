import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import google.generativeai as genai
from bson import ObjectId
from fastapi import HTTPException

from src.ai.constants import MAX_CONVERSATION_MESSAGES, MAX_TOOL_ITERATIONS, MODEL_NAME, SYSTEM_PROMPT
from src.ai.tools import GEMINI_TOOLS, execute_tool
from src.config import settings
from src.database import get_database

_indexes_ready = False
_model: Optional[genai.GenerativeModel] = None


def _get_model() -> genai.GenerativeModel:
    global _model
    if _model is None:
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        _model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            tools=GEMINI_TOOLS,
            system_instruction=SYSTEM_PROMPT,
        )
    return _model


def _sse(event_type: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': event_type, **kwargs})}\n\n"


def _clean(obj) -> object:
    """JSON round-trip strips any proto-typed values that cross the SDK boundary."""
    return json.loads(json.dumps(obj, default=str))


async def _ensure_indexes(db) -> None:
    global _indexes_ready
    if _indexes_ready:
        return
    await db["ai_conversations"].create_index(
        [("user_id", 1), ("updated_at", -1)],
        name="ai_conversations_user_updated",
    )
    _indexes_ready = True


async def agent_stream(
    user_id: str,
    message: str,
    conversation_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    if not settings.GOOGLE_API_KEY:
        yield _sse("error", message="GOOGLE_API_KEY is not configured. Add it to your .env file.")
        return

    db = get_database()
    await _ensure_indexes(db)

    if conversation_id:
        if not ObjectId.is_valid(conversation_id):
            yield _sse("error", message="Invalid conversation ID")
            return
        conv_doc = await db["ai_conversations"].find_one(
            {"_id": ObjectId(conversation_id), "user_id": user_id}
        )
        if not conv_doc:
            yield _sse("error", message="Conversation not found")
            return
        contents = list(conv_doc["messages"])
        title = conv_doc["title"]
        is_new = False
    else:
        contents = []
        title = message[:70].strip()
        is_new = True

    contents.append({"role": "user", "parts": [{"text": message}]})

    try:
        model = _get_model()
    except Exception as exc:
        yield _sse("error", message=f"Failed to initialise AI model: {exc}")
        return

    any_text_yielded = False
    had_tool_calls = False
    last_tool_results: list[dict] = []

    for iteration in range(MAX_TOOL_ITERATIONS):
        text_accumulated: list[str] = []
        function_calls: list[dict] = []

        try:
            # Non-streaming: avoids the Gemini SDK hang where the async chunk
            # iterator never signals EOF when the response contains a function call.
            response = await model.generate_content_async(contents)
        except Exception as exc:
            yield _sse("error", message=str(exc))
            return

        if not response.candidates:
            break

        candidate = response.candidates[0]
        finish = getattr(candidate, "finish_reason", None)
        content_parts = candidate.content.parts if (candidate.content and candidate.content.parts) else []

        if finish and finish.name in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST"):
            yield _sse("error", message="Response filtered by model safety system.")
            return

        for part in content_parts:
            if getattr(part, "thought", False):
                continue
            if getattr(part, "text", None):
                text_accumulated.append(part.text)
                yield _sse("text_delta", text=part.text)
                any_text_yielded = True
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = _clean(dict(fc.args) if fc.args else {})
                function_calls.append({"name": fc.name, "args": args})
                yield _sse("tool_start", tool_name=fc.name, tool_input=args)

        assistant_parts: list[dict] = []
        if text_accumulated:
            assistant_parts.append({"text": "".join(text_accumulated)})
        for fc in function_calls:
            assistant_parts.append({"function_call": {"name": fc["name"], "args": fc["args"]}})

        if not assistant_parts:
            break

        contents.append({"role": "model", "parts": assistant_parts})

        if not function_calls:
            break

        had_tool_calls = True
        last_tool_results = []
        tool_response_parts: list[dict] = []
        for fc in function_calls:
            raw = await execute_tool(user_id, fc["name"], fc["args"])
            result = _clean(raw)
            is_error = "error" in result
            last_tool_results.append({"tool": fc["name"], "result": result})
            yield _sse("tool_result", tool_name=fc["name"], output=result, is_error=is_error)
            tool_response_parts.append({
                "function_response": {"name": fc["name"], "response": {"result": result}}
            })

        contents.append({"role": "user", "parts": tool_response_parts})

    # Gemini 2.5 Flash (thinking model) sometimes produces only internal thought tokens
    # after a tool call with no visible text. Inject a model acknowledgment and a user
    # nudge — this restores the alternating turn structure and reliably triggers a reply.
    if had_tool_calls and not any_text_yielded:
        try:
            # contents ends with: [..., model:fc, user:fr]
            # Append a model stub + user prompt to keep proper turn alternation
            nudge_contents = contents + [
                {"role": "model", "parts": [{"text": "I have retrieved the requested data."}]},
                {"role": "user", "parts": [{"text": "Please give a clear, direct answer based on that data."}]},
            ]
            resp = await model.generate_content_async(nudge_contents)
            if resp.candidates:
                c = resp.candidates[0]
                parts = c.content.parts if (c.content and c.content.parts) else []
                for part in parts:
                    if getattr(part, "thought", False):
                        continue
                    if getattr(part, "text", None):
                        yield _sse("text_delta", text=part.text)
                        any_text_yielded = True
        except Exception as exc:
            pass

    if len(contents) > MAX_CONVERSATION_MESSAGES:
        contents = contents[-MAX_CONVERSATION_MESSAGES:]

    now = datetime.now(timezone.utc)
    if is_new:
        ins = await db["ai_conversations"].insert_one({
            "user_id": user_id,
            "title": title,
            "messages": contents,
            "created_at": now,
            "updated_at": now,
        })
        saved_id = str(ins.inserted_id)
    else:
        await db["ai_conversations"].update_one(
            {"_id": ObjectId(conversation_id)},
            {"$set": {"messages": contents, "updated_at": now}},
        )
        saved_id = conversation_id

    yield _sse("done", conversation_id=saved_id, title=title)


async def list_conversations(user_id: str, skip: int = 0, limit: int = 50) -> dict:
    db = get_database()
    await _ensure_indexes(db)
    total = await db["ai_conversations"].count_documents({"user_id": user_id})
    docs = await db["ai_conversations"].find(
        {"user_id": user_id},
        {"_id": 1, "title": 1, "created_at": 1, "updated_at": 1},
    ).sort("updated_at", -1).skip(skip).limit(limit).to_list(length=limit)
    return {
        "items": [{"id": str(d["_id"]), "title": d["title"], "created_at": d["created_at"], "updated_at": d["updated_at"]} for d in docs],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


async def get_conversation(user_id: str, conversation_id: str) -> dict:
    if not ObjectId.is_valid(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    db = get_database()
    doc = await db["ai_conversations"].find_one({"_id": ObjectId(conversation_id), "user_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "messages": doc["messages"],
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


async def delete_conversation(user_id: str, conversation_id: str) -> None:
    if not ObjectId.is_valid(conversation_id):
        raise HTTPException(status_code=400, detail="Invalid conversation ID")
    db = get_database()
    result = await db["ai_conversations"].delete_one({"_id": ObjectId(conversation_id), "user_id": user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Conversation not found")
