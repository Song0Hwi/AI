"""
AXIS-Y 시계열 분석 대시보드 로컬 실행 서버 (보너스 과제: 분석 결과 서비스화)
실행 방법:
    python app.py
실행 후 브라우저에서 http://localhost:8050 으로 접속하여 기간/조건별 인터랙티브 시계열 탐색이 가능합니다.
"""

import os
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 8050
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            self.path = '/dashboard.html'
        return super().do_GET()


def main():
    url = f"http://localhost:{PORT}/dashboard.html"
    print("=" * 65)
    print(f"AXIS-Y 시계열 리뷰 분석 웹 대시보드 서버가 시작되었습니다.")
    print(f"- 접속 URL: {url}")
    print("- 종료하려면 Ctrl+C 를 누르세요.")
    print("=" * 65)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        server.server_close()


if __name__ == '__main__':
    main()
