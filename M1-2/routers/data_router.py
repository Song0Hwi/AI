"""
시계열 데이터 관리(CRUD) 및 요약/통계/내보내기 라우터 (data_router.py)
- POST   /api/data            : 새 데이터 추가
- GET    /api/data            : 데이터 목록 조회
- GET    /api/data/summary    : 데이터 요약 (시스템 프롬프트 주입용)
- GET    /api/data/statistics : [보너스] 심화 시계열 통계·이동평균·이상치·예측 조회
- GET    /api/data/export     : [보너스] 데이터 CSV / JSON 파일 다운로드
- PUT    /api/data/{id}       : 데이터 수정
- DELETE /api/data/{id}       : 데이터 삭제
"""
import io
import csv
import json
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from schemas import DataCreate, DataUpdate, DataItem, SummaryResponse
from services.firebase_service import firebase_service
from services.analytics_service import analytics_service

router = APIRouter(prefix="/api/data", tags=["Data (시계열 데이터 CRUD & 요약)"])


@router.get(
    "/summary",
    response_model=SummaryResponse,
    summary="데이터 요약 조회 (프롬프트 컨텍스트 주입용)",
)
def get_data_summary():
    """
    저장된 전체 시계열 데이터의 기간(period), 레코드 수(count),
    기본 통계(total, average, max, min, std_dev, cv_percent) 및 최근 추세(trend)를 반환합니다.
    """
    return analytics_service.get_summary()


@router.get(
    "/statistics",
    summary="[보너스] 확장 시계열 통계·이동평균·이상치·예측 지표 조회",
)
def get_data_statistics():
    """
    보너스 과제용 확장 엔드포인트:
    - 연도별/계절별 평균 및 비중
    - 4주/12주 이동평균(MA4, MA12)
    - Z-score 기반 급증/급감 이상치(Outliers) 탐지
    - 향후 4주 베이스라인 예측(Forecast)
    """
    return analytics_service.get_advanced_statistics()


@router.get(
    "/export",
    summary="[보너스] 시계열 데이터 내보내기 (CSV / JSON 다운로드)",
)
def export_data(
    format: str = Query("csv", pattern="^(csv|json)$", description="내보낼 파일 형식 (csv 또는 json)"),
    start_date: Optional[str] = Query(None, description="필터 시작일 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="필터 종료일 (YYYY-MM-DD)"),
):
    items = firebase_service.list_data(start_date=start_date, end_date=end_date)
    if format == "json":
        content = json.dumps(items, ensure_ascii=False, indent=2)
        return Response(
            content=content.encode("utf-8"),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="119_timeseries_export.json"'},
        )

    output = io.StringIO()
    output.write("\ufeff")  # Excel 한글 깨짐 방지 UTF-8 BOM
    writer = csv.DictWriter(
        output,
        fieldnames=["id", "date", "value", "memo", "created_at", "updated_at"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(items)
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="119_timeseries_export.csv"'},
    )


@router.post(
    "",
    response_model=DataItem,
    status_code=status.HTTP_201_CREATED,
    summary="새 시계열 데이터 추가",
)
def create_data_item(payload: DataCreate):
    """(date, value, memo) 형태의 새 시계열 데이터 포인트를 검증 후 Firestore에 추가합니다."""
    created = firebase_service.create_data(
        date=payload.date,
        value=payload.value,
        memo=payload.memo,
    )
    return created


@router.get(
    "",
    response_model=List[DataItem],
    summary="시계열 데이터 목록 조회",
)
def list_data_items(
    start_date: Optional[str] = Query(None, description="조회 시작일 (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="조회 종료일 (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="메모 또는 날짜 검색어"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="최대 조회 개수"),
):
    """저장된 시계열 데이터 목록을 날짜 오름차순으로 조회합니다."""
    return firebase_service.list_data(
        start_date=start_date,
        end_date=end_date,
        search=search,
        limit=limit,
    )


@router.put(
    "/{item_id}",
    response_model=DataItem,
    summary="특정 시계열 데이터 수정",
)
def update_data_item(item_id: str, payload: DataUpdate):
    """지정한 ID의 시계열 데이터(date, value, memo)를 수정합니다."""
    if payload.date is None and payload.value is None and payload.memo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="수정할 필드(date, value, memo 중 최소 1개)를 입력해야 합니다.",
        )
    updated = firebase_service.update_data(
        doc_id=item_id,
        date=payload.date,
        value=payload.value,
        memo=payload.memo,
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"해당 ID의 데이터를 찾을 수 없습니다: {item_id}",
        )
    return updated


@router.delete(
    "/{item_id}",
    summary="특정 시계열 데이터 삭제",
)
def delete_data_item(item_id: str):
    """지정한 ID의 시계열 데이터를 Firestore에서 삭제합니다."""
    deleted = firebase_service.delete_data(item_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"해당 ID의 데이터를 찾을 수 없습니다: {item_id}",
        )
    return {"status": "deleted", "id": item_id, "message": "데이터가 정상적으로 삭제되었습니다."}
