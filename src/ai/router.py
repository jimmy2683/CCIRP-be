from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from src.ai.schemas import ChatRequest, ConversationFull, ConversationMeta
from src.ai.service import agent_stream, delete_conversation, get_conversation, list_conversations
from src.auth.dependencies import get_current_active_user
from src.pagination import PaginatedResponse

router = APIRouter(prefix="/ai", tags=["AI"])


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    current_user: dict = Depends(get_current_active_user),
):
    return StreamingResponse(
        agent_stream(current_user["id"], request.message, request.conversation_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations", response_model=PaginatedResponse[ConversationMeta])
async def list_conversations_endpoint(
    skip: int = 0,
    limit: int = 50,
    current_user: dict = Depends(get_current_active_user),
):
    return await list_conversations(current_user["id"], skip=skip, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationFull)
async def get_conversation_endpoint(
    conversation_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    return await get_conversation(current_user["id"], conversation_id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_endpoint(
    conversation_id: str,
    current_user: dict = Depends(get_current_active_user),
):
    await delete_conversation(current_user["id"], conversation_id)
    return None
