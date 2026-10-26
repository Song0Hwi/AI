/**
 * 프론트엔드 환경 설정 (config.js)
 * - Vercel 배포 환경에서는 window.__ENV__.API_BASE_URL 또는 localStorage 설정값을 사용하며,
 *   로컬 개발 환경에서는 현재 호스트(또는 http://localhost:8000)로 자동 연결됩니다.
 */
window.APP_CONFIG = {
  API_BASE_URL:
    localStorage.getItem("M12_API_BASE_URL") ||
    (window.__ENV__ && window.__ENV__.API_BASE_URL) ||
    (window.location.port === "8000" ? window.location.origin : "http://localhost:8000"),
};
