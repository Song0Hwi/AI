# ============================================================
# A 담당 · 설정 로딩
#
# config.json 은 A 소유다. B/C가 키가 필요하면 A에게 요청한다.
# (INTERFACE.md 7번 - main.py 와 config.json 은 셋 다 건드리면 충돌한다)
# ============================================================

import json
import os

from modules.paths import CHART_DIR, ensure_directories


class ConfigError(Exception):
    """설정이 잘못되었을 때 던진다."""


DEFAULT_CONFIG = {
    "duplicate_policy": "skip",

    "cleaning": {
        # B의 cleaner.py 가 내부에 가진 값과 같은 뜻이지만,
        # B 코드는 상수로 고정되어 있어 config 로 바꿀 수 없다.
        # 여기 값은 A가 직접 처리하는 경로(add 명령)에만 적용된다.
        "min_review_length": 5,
        "rating_min": 1,
        "rating_max": 5,
        "duplicate_keys": ["product_name", "review_text", "review_date"],
    },

    "ai": {
        "model": "gemini-3.6-flash",
        "api_key_env": "GEMINI_API_KEY",
        # extract 프롬프트에 넣을 최대 리뷰 수.
        # 99건을 통째로 넣으면 토큰이 커지고 요약이 뭉개진다.
        "extract_max_reviews": 60,
        # [2026-08-12] batch_size 를 뺐다.
        # C가 analyze_review_batch() 로 직접 묶어 부르고 실패하면
        # 스스로 반으로 쪼갠다. A가 앞에서 또 자르면 그 재시도 폭만
        # 좁아진다. 아무도 읽지 않는 설정을 남겨두면 나중에 값을
        # 바꿔놓고 왜 안 듣는지 찾게 된다.
        # use_mock 도 함께 뺐다 (modules/mock_ai.py 제거).
    },

    "visualization": {
        "save_format": "png",
        "dpi": 150,
    },

    "analysis": {
        "default_limit": 20,
        "top_n": 5,
    },

    # 임계치. 판정 로직과 근거는 modules/stats.py 의 DEFAULT_THRESHOLDS,
    # 대응 절차는 chart/README.md 4.10 절에 있다.
    # 여기 값이 stats 쪽 기본값을 덮어쓴다.
    "alerts": {
        "negative_ratio_warn": 0.15,
        "negative_ratio_critical": 0.30,
        "spike_delta": 0.10,
        "min_bucket_size": 5,
        "group_negative_ratio_warn": 0.30,
        "min_group_size": 5,
        "agreement_warn": 0.60,
        "confidence_warn": 0.65,
    },

    "logging": {
        "level": "INFO",
        "to_file": True,
        "filename": "app.log",
    },
}


ALLOWED_POLICIES = {"skip", "upsert"}

_CACHE = None


def deep_merge(base, override):
    """중첩 dict 를 재귀 병합한다. override 가 우선."""

    result = dict(base)

    for key, value in (override or {}).items():

        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)

        else:
            result[key] = value

    return result


def validate_config(config):
    """치명적인 값만 검사한다. 나머지는 기본값으로 메운다."""

    policy = config.get("duplicate_policy")

    if policy not in ALLOWED_POLICIES:
        raise ConfigError(
            f"duplicate_policy 는 {sorted(ALLOWED_POLICIES)} 중 "
            f"하나여야 합니다 (현재: {policy!r})"
        )

    cleaning = config["cleaning"]

    if cleaning["rating_min"] > cleaning["rating_max"]:
        raise ConfigError(
            "cleaning.rating_min 이 rating_max 보다 큽니다."
        )

    if int(config["ai"]["extract_max_reviews"]) < 1:
        raise ConfigError("ai.extract_max_reviews 는 1 이상이어야 합니다.")

    alerts = config.get("alerts", {})

    for key in ("negative_ratio_warn", "negative_ratio_critical",
                "spike_delta", "group_negative_ratio_warn",
                "agreement_warn", "confidence_warn"):

        value = alerts.get(key)

        if value is not None and not 0.0 <= float(value) <= 1.0:
            raise ConfigError(
                f"alerts.{key} 는 0.0~1.0 사이여야 합니다 (현재: {value})"
            )

    if (
        alerts.get("negative_ratio_critical") is not None
        and alerts.get("negative_ratio_warn") is not None
        and alerts["negative_ratio_critical"] < alerts["negative_ratio_warn"]
    ):
        raise ConfigError(
            "alerts.negative_ratio_critical 이 warn 보다 작습니다. "
            "심각선이 경고선보다 낮으면 심각 경고만 계속 뜹니다."
        )

    if not config["cleaning"]["duplicate_keys"]:
        raise ConfigError("cleaning.duplicate_keys 가 비어 있습니다.")

    return config


def load_config(force_reload=False):
    """
    chart/config.json 을 읽어 기본값과 병합한다.
    파일이 없어도 기본값으로 동작한다.
    """

    global _CACHE

    if _CACHE is not None and not force_reload:
        return _CACHE

    config_path = CHART_DIR / "config.json"
    found = config_path.exists()

    override = {}

    if found:
        try:
            override = json.loads(config_path.read_text(encoding="utf-8"))

        except json.JSONDecodeError as error:
            raise ConfigError(
                f"config.json 을 읽을 수 없습니다 ({config_path}): {error}"
            ) from error

    config = validate_config(deep_merge(DEFAULT_CONFIG, override))

    config["_config_path"] = str(config_path)
    config["_config_file_found"] = found

    ensure_directories()

    _CACHE = config

    return config


def get_api_key(config):
    """
    Gemini API 키를 환경변수에서 읽는다. 없으면 None.

    C의 analyzer.py 는 모듈 로드 시점에 load_dotenv() 를 호출하므로
    .env 파일도 자동으로 반영된다. A는 '키가 있는지'만 미리 확인해
    analyze / extract 를 시작하기 전에 막는 데 쓴다.

    키가 없는 채로 99건을 돌리면 C가 99번 예외를 내고 전부
    failed_ids 로 떨어진다. 그 전에 한 줄로 끊는 편이 낫다.
    """

    try:
        from dotenv import load_dotenv

        load_dotenv()

    except ImportError:
        pass

    env_name = config["ai"].get("api_key_env", "GEMINI_API_KEY")

    return os.environ.get(env_name) or os.environ.get("GOOGLE_API_KEY")
