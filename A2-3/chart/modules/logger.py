# ============================================================
# A 담당 · 로깅 통일 (명세 4.10)
#
# B/C 코드는 print 와 logging 을 섞어 쓰고 있다.
# 그 코드를 고치지 않고도 로그를 한 곳에 모으려면
# 루트 로거를 A가 설정해두면 된다.
#   - C의 analyzer.py 는 logging.getLogger(__name__) 을 쓰므로
#     여기 설정이 그대로 적용된다.
#   - B의 print 는 표준출력으로 남는다. 이건 B 영역이라 건드리지 않는다.
# ============================================================

import logging
import sys
from pathlib import Path


LEVEL_TAG = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}

_CONFIGURED = False


class ConsoleFormatter(logging.Formatter):
    """콘솔에는 시각을 빼고 짧게 찍는다. 파일에는 전체를 남긴다."""

    def format(self, record):
        tag = LEVEL_TAG.get(record.levelno, record.levelname)

        return f"[{tag}] {record.getMessage()}"


def setup_logging(config=None, verbose=False, quiet=False):
    """
    루트 로거를 설정한다. 두 번 불러도 핸들러가 중복되지 않는다.
    """

    global _CONFIGURED

    config = config or {}
    log_config = config.get("logging", {})

    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = getattr(
            logging,
            str(log_config.get("level", "INFO")).upper(),
            logging.INFO,
        )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 재설정 시 기존 핸들러를 걷어낸다.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(ConsoleFormatter())
    root.addHandler(console)

    if log_config.get("to_file", True):
        from modules.paths import LOG_DIR

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = Path(LOG_DIR) / log_config.get("filename", "app.log")

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)-12s %(message)s"
            )
        )
        root.addHandler(file_handler)

    # google-genai / urllib3 의 DEBUG 로그가 화면을 덮는 것을 막는다.
    for noisy in ("google", "google_genai", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True

    return root


def get_logger(name):
    """모듈용 로거를 돌려준다."""

    return logging.getLogger(name)
