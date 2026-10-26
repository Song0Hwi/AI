"""
헤드리스 브라우저(Edge/Chrome)를 이용해 README 제출용 4종 스크린샷을 자동 촬영하는 스크립트
"""
import os
import subprocess
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def main():
    browser = next((p for p in CANDIDATES if os.path.exists(p)), None)
    if not browser:
        print("브라우저 실행 파일을 찾을 수 없습니다.")
        return

    targets = [
        ("01_chat_with_summary.png", "http://127.0.0.1:8000/?view=all"),
        ("02_data_crud.png", "http://127.0.0.1:8000/?view=crud"),
        ("03_conversation_history.png", "http://127.0.0.1:8000/?view=history"),
        ("04_swagger_docs.png", "http://127.0.0.1:8000/docs"),
    ]

    for filename, url in targets:
        out_path = os.path.join(SCREENSHOT_DIR, filename)
        with tempfile.TemporaryDirectory() as tmp_profile:
            cmd = [
                browser,
                "--headless=new",
                f"--user-data-dir={tmp_profile}",
                "--window-size=1600,1080",
                "--hide-scrollbars",
                "--virtual-time-budget=5000",
                f"--screenshot={out_path}",
                url,
            ]
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_path):
            print(f"Captured: {filename} ({os.path.getsize(out_path):,} bytes)")


if __name__ == "__main__":
    main()
