"""
FastAPI 메인 애플리케이션 (main.py)
- 로컬 실행: `uvicorn main:app --reload`
- Swagger UI: http://localhost:8000/docs
- 웹 프론트엔드(바닐라 JS): http://localhost:8000/
"""
from pathlib import Path
from typing import Dict, Any
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings, BASE_DIR
from routers.data_router import router as data_router
from routers.conversations_router import router as conversations_router
from routers.chat_router import router as chat_router
from services.firebase_service import firebase_service, now_iso
from mcp_server import handle_mcp_jsonrpc

app = FastAPI(
    title=settings.PROJECT_TITLE,
    version=settings.PROJECT_VERSION,
    description=settings.PROJECT_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS 설정 (요구사항 3 & 7: 배포 환경에서 프론트엔드-백엔드 통신 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(data_router)
app.include_router(conversations_router)
app.include_router(chat_router)


@app.get("/api/health", tags=["System (헬스체크 & 콜드스타트 대응)"])
def health_check():
    """
    백엔드 서버 상태 및 Firestore 연결 상태를 확인합니다.
    (Render 무료 티어의 슬립/콜드스타트 깨우기 및 상태 표시용)
    """
    return {
        "status": "ok",
        "timestamp": now_iso(),
        "firestore_connected": firebase_service.connected,
        "firebase_project_id": firebase_service.project_id,
        "data_count": len(firebase_service.list_data()),
        "conversations_count": len(firebase_service.list_conversations()),
        "cold_start_notice": "Render 무료 티어는 15분 미사용 시 슬립 모드로 전환되어 첫 요청에 약 30~50초가 소요될 수 있습니다.",
    }


@app.post("/api/mcp", tags=["Bonus: MCP & GPT Actions (멀티채널 도구 연동)"])
def mcp_http_endpoint(payload: Dict[str, Any] = Body(...)):
    """
    [보너스 과제 1] 외부 MCP 클라이언트 또는 멀티채널 에이전트가 JSON-RPC 2.0으로
    내부 도구(get_data_summary, search_timeseries_data, get_advanced_statistics 등)를 호출하는 엔드포인트입니다.
    """
    return handle_mcp_jsonrpc(payload)


# 바닐라 HTML/CSS/JS 프론트엔드 정적 파일 서빙 (로컬 단일 서버 및 Vercel 별도 배포 모두 지원)
FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {
        "message": "119 AI 데이터 비서 API 서버가 실행 중입니다.",
        "docs": "/docs",
        "health": "/api/health",
    }


@app.get("/{filename:path}", include_in_schema=False)
def serve_frontend_assets(filename: str):
    target = (FRONTEND_DIR / filename).resolve()
    if FRONTEND_DIR.resolve() in target.parents and target.is_file():
        return FileResponse(str(target))
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"detail": "Not Found"}
