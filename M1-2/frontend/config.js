/**
 * 프론트엔드 환경 설정 (config.js)
 * - Vercel 배포 환경(https://ai-frontend-eta-steel.vercel.app)에서는
 *   Render 백엔드(https://ai-e6ub.onrender.com)로 자동 연결되며,
 *   로컬 개발 환경(localhost / 127.0.0.1)에서는 로컬 백엔드로 연결됩니다.
 */
const isLocalHost =
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1";

window.APP_CONFIG = {
  API_BASE_URL:
    localStorage.getItem("M12_API_BASE_URL") ||
    (window.__ENV__ && window.__ENV__.API_BASE_URL) ||
    (isLocalHost
      ? window.location.port === "8000"
        ? window.location.origin
        : "http://localhost:8000"
      : "https://ai-e6ub.onrender.com"),
};
