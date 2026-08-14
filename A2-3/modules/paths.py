# ============================================================
# A 담당 · 경로 해석과 B/C 모듈 로더
#
# 폴더 3개가 곧 담당자 3명이다. 상수 이름을 폴더 이름과 1:1 로 맞췄다.
#
#   team7/
#   ├── chart/    ← A(영휘)  이 파일이 있는 곳
#   ├── prompt/   ← C(민규)
#   └── source/   ← B(세인)
#
# 이 파일이 존재하는 이유
#   구조가 확정됐으니 경로 상수는 각자 쓰는 곳에 박아도 된다.
#   그런데 이 파일이 남아 있는 진짜 이유는 상수가 아니라 로더다.
#
#   B의 코드는 source/src/ 에, C의 코드는 prompt/ 에 있는데
#   두 폴더 모두 __init__.py 가 없어서 평범한 import 가 안 된다.
#   A가 __init__.py 를 넣으면 그 폴더는 더 이상 그 사람만의 것이 아니게
#   되고 머지 충돌이 시작된다. (tests 에 그 조항이 있다)
#   그래서 패키지 import 대신 "파일 경로로 직접 모듈을 읽어오는" 로더를
#   A쪽에 둔다.
#
#   이렇게 하면
#     - B/C 폴더에 파일이 단 한 줄도 추가되지 않는다
#     - sys.path 를 오염시키지 않아 이름 충돌(cleaner 가 둘)이 안 난다
#     - B/C가 파일을 갱신하면 그대로 반영된다
#
#   덤으로 이 파일은 modules 안에서 다른 modules 를 import 하지 않는
#   유일한 파일이다. 그래서 logger·config·database 가 순환 참조 걱정 없이
#   가져다 쓴다. 합칠 곳을 찾는다면 그 성질부터 깨진다.
# ============================================================

import importlib.util
import sys
from pathlib import Path


# chart/modules/paths.py -> chart/modules -> chart -> 레포 루트
CHART_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CHART_DIR.parent

# B(세인) 영역 — 예전 data/ 폴더가 source/ 로 옮겨왔다.
# 내부 구조(src·raw·clean)는 그대로라 B 코드의 경로 가정이 살아 있다.
# source/input/ 은 사람이 CLI 에 직접 적는 자리라 상수로 두지 않는다.
SOURCE_DIR = REPO_ROOT / "source"
DATA_SRC_DIR = SOURCE_DIR / "src"
DATA_RAW_DIR = SOURCE_DIR / "raw"
DATA_CLEAN_DIR = SOURCE_DIR / "clean"

# C(민규) 영역
PROMPT_DIR = REPO_ROOT / "prompt"

# A(영휘) 영역 — 실행 시 생성된다. .gitignore 에 있다.
DB_DIR = CHART_DIR / "db"
OUTPUT_DIR = CHART_DIR / "output"
LOG_DIR = CHART_DIR / "logs"


class ModuleNotProvided(Exception):
    """B 또는 C의 파일이 아직 없을 때 던진다. 치명적 오류가 아니다."""


# 로드한 모듈을 캐시한다. 같은 파일을 두 번 exec 하면
# 모듈 전역(genai 클라이언트 등)이 두 벌 생긴다.
_CACHE = {}


def _load_module_from_file(alias, directory, filename):
    """directory/filename 을 모듈로 읽어온다."""

    if alias in _CACHE:
        return _CACHE[alias]

    path = directory / filename

    if not path.exists():
        raise ModuleNotProvided(
            f"{directory.name}/{filename} 가 아직 없습니다. "
            f"(찾아본 경로: {path})"
        )

    spec = importlib.util.spec_from_file_location(alias, path)

    if spec is None or spec.loader is None:
        raise ModuleNotProvided(f"모듈을 읽을 수 없습니다: {path}")

    module = importlib.util.module_from_spec(spec)

    # 모듈 안에서 자기 자신을 다시 import 하는 경우를 대비해 먼저 등록한다.
    sys.modules[alias] = module
    spec.loader.exec_module(module)

    _CACHE[alias] = module

    return module


# ------------------------------------------------------------ B (세인)

def load_b_importer():
    """source/src/importer.py — import_reviews(file_path, output_path)"""

    return _load_module_from_file("b_importer", DATA_SRC_DIR, "importer.py")


def load_b_cleaner():
    """source/src/cleaner.py — clean_reviews(input_path, output_path)"""

    return _load_module_from_file("b_cleaner", DATA_SRC_DIR, "cleaner.py")


# 차트(visualizer)와 내보내기(exporter)는 A로 이관되어
# chart/modules/ 안에 있다. 여기 로더가 필요 없다.


# ------------------------------------------------------------ C (민규)

def load_c_analyzer():
    """prompt/analyzer.py — analyze_review(text), analyze_reviews(reviews)"""

    return _load_module_from_file("c_analyzer", PROMPT_DIR, "analyzer.py")


def load_c_extractor():
    """prompt/extractor.py — extract_insights(texts)"""

    return _load_module_from_file("c_extractor", PROMPT_DIR, "extractor.py")


def load_c_reporter():
    """prompt/reporter.py — generate_markdown_report(...)"""

    return _load_module_from_file("c_reporter", PROMPT_DIR, "reporter.py")


# ------------------------------------------------------------ 공용

def ensure_directories():
    """A가 쓰는 폴더를 만든다. B 영역 폴더는 B가 쓰는 경로라 함께 만들어 둔다."""

    for directory in (DB_DIR, OUTPUT_DIR, LOG_DIR,
                      DATA_RAW_DIR, DATA_CLEAN_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def describe_layout():
    """status 명령에서 어느 폴더를 보고 있는지 보여준다."""

    return {
        "repo_root": REPO_ROOT,
        "chart (A)": CHART_DIR,
        "prompt (C)": PROMPT_DIR,
        "source (B)": SOURCE_DIR,
    }
