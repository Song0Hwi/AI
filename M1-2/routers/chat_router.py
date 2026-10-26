"""
데이터 기반 AI 챗봇 라우터 (chat_router.py)
- POST /api/chat       : 데이터 요약 컨텍스트 주입 + Function Calling 도구 호출 + GPT 응답 + 대화 자동 저장
- GET  /api/chat/tools : [보너스] 등록된 AI 도구(Function Calling / MCP) 스키마 및 호출 테스트 엔드포인트
"""
from typing import Optional
from fastapi import APIRouter, Query

from schemas import ChatRequest, ChatResponse
from services.ai_service import ai_service, OPENAI_TOOLS_SCHEMA

router = APIRouter(prefix="/api/chat", tags=["AI Chat (컨텍스트 주입 & Function Calling 챗봇)"])


@router.post(
    "",
    response_model=ChatResponse,
    summary="데이터 기반 맞춤형 AI 채팅 (컨텍스트 주입 + 자동 저장)",
)
def chat_with_ai(payload: ChatRequest):
    """
    동작 흐름:
    1. 데이터 요약 조회 (`/api/data/summary`)
    2. 요약을 시스템 프롬프트에 삽입 (Context Injection)
    3. [보너스] 질문 의도에 맞는 내부 도구(Function Calling) 자동 실행 및 근거 기록
    4. AI 모델 호출 및 맞춤형 응답 생성
    5. 대화 내용을 `conversations` 컬렉션에 자동 저장
    """
    result = ai_service.chat(
        user_message=payload.message,
        conversation_id=payload.conversation_id,
        use_tools=payload.use_tools,
    )
    return result


@router.get(
    "/tools",
    summary="[보너스] AI 도구 호출(Function Calling) 스키마 및 멀티채널 연동 명세 조회",
)
def get_registered_tools(
    test_tool: Optional[str] = Query(
        None,
        description="즉시 실행 테스트할 도구 이름 (예: get_data_summary, get_advanced_statistics)",
    ),
):
    """
    GPT Function Calling 및 외부 채널(MCP Server / GPT Actions)에서 사용하는 도구 스키마 목록을 반환하며,
    선택적으로 특정 도구의 실행 결과를 즉시 검증할 수 있습니다.
    """
    test_output = None
    if test_tool:
        test_output = ai_service.execute_tool(test_tool, {})

    return {
        "protocol": "OpenAI Function Calling & MCP (Model Context Protocol) / GPT Actions",
        "tools_count": len(OPENAI_TOOLS_SCHEMA),
        "tools_schema": OPENAI_TOOLS_SCHEMA,
        "test_execution": {
            "tool": test_tool,
            "output": test_output,
        } if test_tool else None,
    }
