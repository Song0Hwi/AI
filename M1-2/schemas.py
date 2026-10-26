"""
Pydantic 데이터 검증 스키마 (Schemas)
- API 요청/응답 데이터의 타입, 범위, 날짜 형식을 검증하여 데이터 무결성을 보장합니다.
"""
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_date_format(v: str) -> str:
    v = v.strip()
    if not DATE_PATTERN.match(v):
        raise ValueError("날짜는 'YYYY-MM-DD' 형식이어야 합니다. (예: 2025-03-15)")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"유효하지 않은 날짜입니다: {v}") from e
    return v


class DataCreate(BaseModel):
    date: str = Field(..., description="데이터 기준 일자 (YYYY-MM-DD)", examples=["2025-09-15"])
    value: float = Field(..., ge=0, description="시계열 수치 값 (예: 119 신고접수 건수)", examples=[16420])
    memo: str = Field(
        default="",
        max_length=500,
        description="데이터 관련 메모 (계절, 최다 지역, 특이사항 등)",
        examples=["[가을] 전국 119 주간 접수 | 최다: 경기도(28.1%)·서울(19.0%) | 평균 현장도착: 7.4분"],
    )

    @field_validator("date")
    @classmethod
    def check_date(cls, v: str) -> str:
        return validate_date_format(v)


class DataUpdate(BaseModel):
    date: Optional[str] = Field(None, description="수정할 기준 일자 (YYYY-MM-DD)")
    value: Optional[float] = Field(None, ge=0, description="수정할 수치 값 (0 이상)")
    memo: Optional[str] = Field(None, max_length=500, description="수정할 메모")

    @field_validator("date")
    @classmethod
    def check_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return validate_date_format(v)


class DataItem(BaseModel):
    id: str = Field(..., description="문서 고유 ID")
    date: str = Field(..., description="기준 일자 (YYYY-MM-DD)")
    value: float = Field(..., description="시계열 수치 값")
    memo: str = Field(default="", description="메모")
    created_at: Optional[str] = Field(None, description="생성 일시 (ISO 8601)")
    updated_at: Optional[str] = Field(None, description="수정 일시 (ISO 8601)")


class MetricsModel(BaseModel):
    total: float = Field(..., description="전체 합계")
    average: float = Field(..., description="전체 평균")
    max: float = Field(..., description="최댓값")
    min: float = Field(..., description="최솟값")
    max_date: Optional[str] = Field(None, description="최댓값 발생 일자")
    min_date: Optional[str] = Field(None, description="최솟값 발생 일자")
    std_dev: Optional[float] = Field(None, description="표준편차 (변동성)")
    cv_percent: Optional[float] = Field(None, description="변동계수 CV (%)")


class SummaryResponse(BaseModel):
    period: str = Field(..., description="데이터 기간 (예: 2022-01 ~ 2025-09)")
    count: int = Field(..., description="총 데이터 포인트 개수")
    metrics: MetricsModel = Field(..., description="핵심 통계 지표 (합계, 평균, 최대, 최소 등)")
    trend: str = Field(..., description="최근 추세 요약 (상승/하락/유지 및 변화율)")
    recent_average: Optional[float] = Field(None, description="최근 구간 평균")
    recent_change_pct: Optional[float] = Field(None, description="이전 구간 대비 최근 변화율 (%)")
    highlights: Optional[List[str]] = Field(default_factory=list, description="주요 인사이트 요약 리스트")


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$", description="메시지 역할 (user/assistant/system)")
    content: str = Field(..., min_length=1, description="메시지 본문")
    timestamp: Optional[str] = Field(None, description="메시지 생성 시각")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(None, description="호출된 AI 도구(Function Calling) 이력")


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="사용자 자연어 질문",
        examples=["최근 신고접수 추세와 가장 신고가 많았던 시기는 언제야?"],
    )
    conversation_id: Optional[str] = Field(
        None,
        description="이어갈 대화 ID (없으면 새 대화 자동 생성)",
    )
    use_tools: bool = Field(
        default=True,
        description="보너스 기능: AI 도구 호출(Function Calling) 활성화 여부",
    )


class ChatResponse(BaseModel):
    reply: str = Field(..., description="데이터 요약 및 도구 호출 결과가 반영된 AI 답변")
    conversation_id: str = Field(..., description="자동 저장된 대화 ID")
    conversation_title: str = Field(..., description="대화 제목")
    summary_injected: SummaryResponse = Field(..., description="시스템 프롬프트에 주입된 데이터 요약")
    tool_calls_used: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="보너스 기능: AI가 질문 해결을 위해 호출한 도구(Function Calling) 근거 및 결과",
    )
    model_used: str = Field(..., description="응답 생성에 사용된 AI 모델")


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=200, description="대화 제목 (미입력 시 첫 질문 기반 자동 생성)")
    messages: List[ChatMessage] = Field(..., min_length=1, description="대화 메시지 목록")


class ConversationItem(BaseModel):
    id: str = Field(..., description="대화 고유 ID")
    title: str = Field(..., description="대화 제목")
    messages: List[ChatMessage] = Field(default_factory=list, description="대화 메시지 전체 목록")
    message_count: int = Field(..., description="메시지 개수")
    created_at: str = Field(..., description="생성 시각")
    updated_at: str = Field(..., description="최근 업데이트 시각")
