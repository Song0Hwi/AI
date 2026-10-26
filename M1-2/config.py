"""
환경 변수 및 애플리케이션 전역 설정 모듈
- .env 파일에서 환경 변수를 로드하고 보안 키 및 CORS 설정을 관리합니다.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    PROJECT_TITLE: str = "119 AI 데이터 비서 (시계열 분석 & 맞춤형 AI 챗봇)"
    PROJECT_VERSION: str = "1.0.0"
    PROJECT_DESCRIPTION: str = (
        "소방청 전국 119 신고접수 시계열 데이터(2022~2025)를 기반으로 "
        "Firestore CRUD, 시계열 요약/통계 분석, 컨텍스트 주입 및 Function Calling 기반 AI 챗봇을 제공하는 FastAPI 백엔드"
    )

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

    FIREBASE_SERVICE_ACCOUNT_JSON: str = os.getenv(
        "FIREBASE_SERVICE_ACCOUNT_JSON", "./serviceAccountKey.json"
    ).strip()

    API_BASE_URL: str = os.getenv("API_BASE_URL", "http://localhost:8000").strip()
    ALLOWED_ORIGINS_RAW: str = os.getenv("ALLOWED_ORIGINS", "*").strip()
    PORT: int = int(os.getenv("PORT", "8000"))

    @property
    def allowed_origins(self) -> list[str]:
        if not self.ALLOWED_ORIGINS_RAW or self.ALLOWED_ORIGINS_RAW == "*":
            return ["*"]
        return [o.strip() for o in self.ALLOWED_ORIGINS_RAW.split(",") if o.strip()]


settings = Settings()
