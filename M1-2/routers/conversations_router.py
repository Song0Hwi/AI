"""
대화 기록(Conversations) 관리 라우터 (conversations_router.py)
- POST   /api/conversations      : 대화 저장
- GET    /api/conversations      : 대화 목록 조회 (messages 포함 여부 제어 가능)
- GET    /api/conversations/{id} : 특정 대화의 전체 messages 상세 조회
- DELETE /api/conversations/{id} : 특정 대화 삭제
"""
from typing import List
from fastapi import APIRouter, HTTPException, Query, status

from schemas import ConversationCreate, ConversationItem
from services.firebase_service import firebase_service

router = APIRouter(prefix="/api/conversations", tags=["Conversations (대화 기록 저장 & 불러오기)"])


@router.post(
    "",
    response_model=ConversationItem,
    status_code=status.HTTP_201_CREATED,
    summary="대화 기록 저장",
)
def create_conversation(payload: ConversationCreate):
    """대화 메시지 목록과 제목을 Firestore 'conversations' 컬렉션에 저장합니다."""
    raw_messages = [m.model_dump() for m in payload.messages]
    saved = firebase_service.save_conversation(
        messages=raw_messages,
        title=payload.title,
    )
    return saved


@router.get(
    "",
    response_model=List[ConversationItem],
    summary="대화 기록 목록 조회",
)
def list_conversations(
    include_messages: bool = Query(
        True,
        description="응답에 전체 messages 배열 포함 여부 (기본값 True로 목록 조회 및 즉시 미리보기 모두 지원)",
    ),
):
    """
    저장된 대화 목록을 최신 업데이트 순으로 반환합니다.
    - 요구사항 6-A(/api/conversations/{id})와 6-B(목록 응답의 messages 포함 여부 정의)를 모두 만족합니다.
    """
    convs = firebase_service.list_conversations()
    if include_messages:
        return convs
    return [
        {
            **c,
            "messages": [],
        }
        for c in convs
    ]


@router.get(
    "/{conversation_id}",
    response_model=ConversationItem,
    summary="특정 대화 상세 조회 (대화 불러오기)",
)
def get_conversation_detail(conversation_id: str):
    """특정 대화 ID의 전체 messages를 조회하여 화면에 재표시합니다."""
    conv = firebase_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"해당 ID의 대화를 찾을 수 없습니다: {conversation_id}",
        )
    return conv


@router.delete(
    "/{conversation_id}",
    summary="특정 대화 기록 삭제",
)
def delete_conversation(conversation_id: str):
    """지정한 ID의 대화 기록을 삭제합니다."""
    deleted = firebase_service.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"해당 ID의 대화를 찾을 수 없습니다: {conversation_id}",
        )
    return {
        "status": "deleted",
        "id": conversation_id,
        "message": "대화 기록이 정상적으로 삭제되었습니다.",
    }
