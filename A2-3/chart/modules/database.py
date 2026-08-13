# ============================================================
# A 담당 · SQLite 저장소
#
# 원본(A 1차본) 대비 바뀐 점
#   [변경] reviews 에 skin_type 컬럼 추가
#          - B의 clean 데이터가 rating/review_text/review_date/
#            product_name/skin_type 5개 필드다. skin_type 을 버리면
#            B가 정제한 정보를 A가 도로 잃는다.
#   [변경] make_review_hash 를 이 파일 안으로 가져왔다.
#          INTERFACE.md 2번은 "해시는 cleaner.make_review_hash() 로 만든다"
#          였지만 B의 cleaner.py 에 그 함수가 없다. 한동안 modules/hashing.py
#          에 따로 뒀는데, 부르는 곳이 여기 한 군데뿐이고 해시는 저장 계층의
#          관심사라 2026-08-12 에 합쳤다.
#   [추가] migrate_schema() — 기존 DB 파일에 skin_type 이 없으면 붙인다.
#
# 테이블 구성
#   raw_reviews : 원본 그대로 보관. 정제 규칙을 바꿔 다시 돌릴 때 쓴다.
#   reviews     : 정제본. review_hash UNIQUE.
#   analyses    : 감정 분석 결과. review_id UNIQUE (리뷰 1건당 최신 1건).
#   extractions : 키워드/요약 추출 결과.
#
# 중복 처리를 DB에서 하는 이유
#   B의 cleaner 는 '이번 파일 안의 중복'만 볼 수 있다.
#   '이미 DB에 저장된 중복'은 DB만 안다.
#   그래서 reviews.review_hash 에 UNIQUE 를 걸고 그 위에서
#       skip   -> INSERT OR IGNORE
#       upsert -> INSERT ... ON CONFLICT DO UPDATE
#   로 갈라 처리한다. 두 경우 모두 판정 근거는 review_hash 하나다.
# ============================================================

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from modules.logger import get_logger
from modules.paths import DB_DIR, ensure_directories


logger = get_logger("database")


# ============================================================
# 중복 판정 해시
# ============================================================
#
# 해시 계산이 A쪽에 있는 이유는 두 가지다.
#   1. 판정 근거가 한 곳(reviews.review_hash UNIQUE)에만 있어야
#      'skip / upsert' 정책이 어긋나지 않는다.
#   2. B는 '이번 파일 안의 중복'만 볼 수 있고
#      '이미 DB에 있는 중복'은 DB만 안다.
#
# 세 컬럼에 그냥 UNIQUE(product_name, review_text, review_date) 를 걸면
# 해시 없이도 될 것 같지만 두 가지가 새어 나간다.
#   · 정규화 — "좋아요" 와 "좋아요 " 가 다른 행이 된다.
#     같은 CSV 를 두 번 넣을 때마다 DB가 불어난다.
#   · NULL — SQLite 의 UNIQUE 는 NULL 을 서로 다른 값으로 본다.
#     `add -t "..."` 를 --product 없이 두 번 치면 composite UNIQUE 는
#     못 막는다. 해시는 None 을 "" 로 정규화해서 막는다.
#
# 중요: B의 dedup 키 순서와 여기 키 목록은 같은 세 필드다.
#       (product_name, review_text, review_date)
#       B가 파일 안에서 지운 중복과 A가 DB에서 막는 중복의 기준이 같다.

WHITESPACE = re.compile(r"\s+")

DUPLICATE_KEYS = ["product_name", "review_text", "review_date"]


def normalize_value(value):
    """
    해시 입력값을 정규화한다.

    연속 공백을 하나로 줄이고 소문자로 만든다.
    이걸 하지 않으면 "좋아요" 와 "좋아요 " 가 다른 리뷰가 된다.
    """

    if value is None:
        return ""

    return WHITESPACE.sub(" ", str(value)).strip().lower()


def make_review_hash(record, keys=None):
    """
    리뷰 1건의 중복 판정용 SHA-256 해시를 만든다.

    keys 기본값은 (product_name, review_text, review_date).

    review_text 단독으로 잡으면 서로 다른 사람이 다른 제품에 남긴
    "좋아요" 가 전부 한 건으로 뭉개진다. 그래서 제품과 날짜를 함께 건다.
    """

    joined = "\x1f".join(
        normalize_value(record.get(key)) for key in (keys or DUPLICATE_KEYS)
    )

    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS raw_reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    payload     TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    review_hash  TEXT NOT NULL UNIQUE,
    product_name TEXT,
    review_text  TEXT NOT NULL,
    rating       INTEGER,
    review_date  TEXT,
    skin_type    TEXT,
    source_file  TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_date    ON reviews(review_date);
CREATE INDEX IF NOT EXISTS idx_reviews_rating  ON reviews(rating);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_name);
CREATE INDEX IF NOT EXISTS idx_reviews_skin    ON reviews(skin_type);

CREATE TABLE IF NOT EXISTS analyses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id   INTEGER NOT NULL UNIQUE
                REFERENCES reviews(id) ON DELETE CASCADE,
    sentiment   TEXT NOT NULL
                CHECK(sentiment IN ('positive', 'negative', 'neutral')),
    confidence  REAL NOT NULL CHECK(confidence BETWEEN 0.0 AND 1.0),
    language    TEXT,
    model       TEXT,
    analyzed_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_analyses_sentiment ON analyses(sentiment);

CREATE TABLE IF NOT EXISTS extractions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scope             TEXT NOT NULL,
    review_count      INTEGER NOT NULL,
    positive_keywords TEXT,
    negative_keywords TEXT,
    summary           TEXT,
    improvements      TEXT,
    model             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


# 정렬 가능한 컬럼 화이트리스트.
#
# 컬럼명은 파라미터 바인딩(?)이 안 되므로 문자열로 끼워 넣어야 한다.
# 사용자 입력을 그대로 쓰면 SQL 인젝션이 된다.
# 그리고 반드시 테이블 별칭을 붙인다. reviews 와 analyses 양쪽에 id가 있어
# 그냥 "id" 라고 쓰면 SQLite 가 ambiguous column name 오류를 낸다.
ORDER_COLUMNS = {
    "id": "r.id",
    "rating": "r.rating",
    "review_date": "r.review_date",
    "sentiment": "a.sentiment",
    "confidence": "a.confidence",
}


class StorageError(Exception):
    """DB 파일을 열 수 없을 때. 원인과 해결책을 함께 담는다."""


def get_db_path():
    """
    SQLite 파일 경로. 우선순위는 환경변수 > config > 기본값.

    경로를 바꿀 수 있어야 하는 이유
      SQLite 는 일반 파일 쓰기보다 요구사항이 많다(바이트 범위 잠금, fsync,
      부분 쓰기). OneDrive·Google Drive·네트워크 드라이브·WSL 마운트 위에
      DB를 두면 파일 복사는 되는데 DB만
          sqlite3.OperationalError: disk I/O error
      로 죽는다. 레포를 동기화 폴더에 두는 건 흔한 일이라,
      DB만 로컬 디스크로 빼낼 수 있게 해둔다.

          set REVIEW_DB_PATH=C:\\temp\\reviews.db      (Windows)
          export REVIEW_DB_PATH=/tmp/reviews.db        (macOS/Linux)
    """

    override = os.environ.get("REVIEW_DB_PATH")

    if override:
        return Path(override).expanduser()

    try:
        from modules.config import load_config

        configured = load_config().get("database", {}).get("path")

        if configured:
            return Path(configured).expanduser()

    except Exception:
        # 설정을 못 읽어도 DB는 열려야 한다. 기본값으로 간다.
        pass

    return DB_DIR / "reviews.db"


# SQLite 가 파일 시스템 때문에 죽을 때 나오는 메시지들.
# 문법 오류나 스키마 문제와 구분해서 안내를 다르게 하려는 것이다.
FILESYSTEM_HINTS = (
    "disk i/o error",
    "unable to open database file",
    "database is locked",
    "attempt to write a readonly database",
)


def _storage_error(path, error):
    """파일 시스템 문제를 사람이 읽을 수 있는 안내로 바꾼다."""

    return StorageError(
        f"DB 파일을 열 수 없습니다: {path}\n"
        f"  원인: {error}\n"
        f"  이 경로가 OneDrive·Google Drive·네트워크 드라이브·WSL 마운트 위에\n"
        f"  있으면 파일 복사는 되지만 SQLite 는 동작하지 않습니다.\n"
        f"  DB만 로컬 디스크로 옮기면 해결됩니다:\n"
        f"    Windows       set REVIEW_DB_PATH=C:\\temp\\reviews.db\n"
        f"    macOS/Linux   export REVIEW_DB_PATH=~/reviews.db\n"
        f"  또는 config.json 에  \"database\": {{\"path\": \"...\"}}  를 넣으세요."
    )


# WAL 모드를 쓸 수 있는지 한 번만 확인하고 기억한다.
#
# WAL 은 읽기와 쓰기가 서로를 막지 않아 기본값보다 낫지만,
# 별도의 -shm 공유 메모리 파일과 mmap 을 요구한다.
# OneDrive·Google Drive·네트워크 드라이브·WSL 마운트처럼
# 그걸 지원하지 않는 파일 시스템에서는 연결 자체가
#     sqlite3.OperationalError: disk I/O error
# 로 죽는다. DB를 저장소 동기화 폴더에 두는 건 흔한 일이라
# 실패하면 조용히 기본 저널 모드로 내려간다.
#
# 이 CLI 는 한 번에 한 프로세스만 돌므로 WAL 이 없어도 기능 손실이 없다.
_WAL_STATE = {}


def _apply_pragmas(connection, key):
    """연결에 PRAGMA 를 건다. WAL 이 안 되면 한 번만 경고하고 넘어간다."""

    connection.execute("PRAGMA foreign_keys = ON")

    if _WAL_STATE.get(key) is False:
        return

    try:
        connection.execute("PRAGMA journal_mode = WAL").fetchone()
        _WAL_STATE[key] = True

    except sqlite3.Error as error:

        if key not in _WAL_STATE:
            logger.debug(
                "WAL 모드를 쓸 수 없어 기본 저널 모드로 동작합니다 "
                "(동기화 폴더/네트워크 드라이브에서 정상): %s", error
            )

        _WAL_STATE[key] = False


@contextmanager
def get_connection(db_path=None):
    """
    커밋/롤백/close 를 자동 처리하는 연결 컨텍스트.

    with 블록을 정상 통과하면 commit,
    예외가 나면 rollback 후 예외를 그대로 올려보낸다.
    """

    ensure_directories()

    resolved = Path(db_path or get_db_path())

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(resolved))

    except (sqlite3.Error, OSError) as error:
        raise _storage_error(resolved, error) from error

    connection.row_factory = sqlite3.Row

    try:
        _apply_pragmas(connection, str(resolved))

        yield connection
        connection.commit()

    except sqlite3.OperationalError as error:

        connection.rollback()

        # 파일 시스템이 원인일 때만 안내로 바꾼다.
        # SQL 문법 오류까지 "OneDrive 를 확인하세요" 로 덮으면 더 헷갈린다.
        if any(hint in str(error).lower() for hint in FILESYSTEM_HINTS):
            raise _storage_error(resolved, error) from error

        raise

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def migrate_schema(db_path=None):
    """
    이미 만들어진 DB 파일에 새 컬럼을 붙인다.

    skin_type 은 B의 clean 데이터를 보고 뒤늦게 추가한 컬럼이다.
    기존 DB를 지우지 않고 이어서 쓸 수 있게 해둔다.
    """

    with get_connection(db_path) as connection:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(reviews)")
        }

        if columns and "skin_type" not in columns:
            connection.execute("ALTER TABLE reviews ADD COLUMN skin_type TEXT")
            logger.info("reviews 테이블에 skin_type 컬럼을 추가했습니다.")


def init_db(db_path=None):
    """스키마를 생성한다. 이미 있으면 마이그레이션만 확인한다."""

    with get_connection(db_path) as connection:
        connection.executescript(SCHEMA)

    migrate_schema(db_path)

    logger.debug("스키마 초기화 완료: %s", db_path or get_db_path())


def save_raw(records, source_file, db_path=None):
    """원본 데이터를 가공 없이 JSON 문자열로 저장한다."""

    payloads = [
        (source_file, json.dumps(record, ensure_ascii=False, default=str))
        for record in records
    ]

    if not payloads:
        return 0

    with get_connection(db_path) as connection:
        connection.executemany(
            "INSERT INTO raw_reviews (source_file, payload) VALUES (?, ?)",
            payloads,
        )

    logger.info("raw 저장소에 %d건 저장", len(payloads))

    return len(payloads)


def clear_raw(db_path=None):
    """raw 저장소를 비운다. 같은 파일을 두 번 import 할 때 쓴다."""

    with get_connection(db_path) as connection:
        connection.execute("DELETE FROM raw_reviews")


def save_clean(records, policy, duplicate_keys,
               source_file="", db_path=None):
    """
    정제된 리뷰를 저장한다. 중복 정책에 따라 SQL 이 달라진다.

      skip   : 이미 있으면 무시하고 지나간다
      upsert : 이미 있으면 내용을 최신 값으로 갱신한다

    반환 예: {"inserted": 34, "updated": 0, "skipped": 2, "total": 36}
    """

    if policy not in ("skip", "upsert"):
        raise ValueError(f"알 수 없는 중복 정책입니다: {policy}")

    result = {
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "total": len(records),
    }

    if not records:
        return result

    columns = (
        "review_hash, product_name, review_text, "
        "rating, review_date, skin_type, source_file"
    )
    values = (
        ":review_hash, :product_name, :review_text, "
        ":rating, :review_date, :skin_type, :source_file"
    )

    if policy == "skip":
        sql = f"INSERT OR IGNORE INTO reviews ({columns}) VALUES ({values})"

    else:
        sql = f"""
            INSERT INTO reviews ({columns}) VALUES ({values})
            ON CONFLICT(review_hash) DO UPDATE SET
                product_name = excluded.product_name,
                review_text  = excluded.review_text,
                rating       = excluded.rating,
                review_date  = excluded.review_date,
                skin_type    = excluded.skin_type,
                source_file  = excluded.source_file,
                updated_at   = datetime('now', 'localtime')
        """

    with get_connection(db_path) as connection:

        for record in records:

            row = {
                "review_hash": (
                    record.get("review_hash")
                    or make_review_hash(record, duplicate_keys)
                ),
                "product_name": record.get("product_name"),
                "review_text": record["review_text"],
                "rating": record.get("rating"),
                "review_date": record.get("review_date"),
                "skin_type": record.get("skin_type"),
                "source_file": source_file,
            }

            if policy == "upsert":
                # 삽입인지 갱신인지 미리 확인해 둔다.
                # created_at == updated_at 비교로 판별하면
                # 같은 초에 삽입되고 갱신될 때 구분이 안 된다.
                # (SQLite datetime() 은 초 단위다.)
                already_exists = connection.execute(
                    "SELECT 1 FROM reviews WHERE review_hash = ?",
                    (row["review_hash"],),
                ).fetchone() is not None

            cursor = connection.execute(sql, row)

            if policy == "skip":

                if cursor.rowcount == 0:
                    result["skipped"] += 1
                else:
                    result["inserted"] += 1

            else:

                if already_exists:
                    result["updated"] += 1
                else:
                    result["inserted"] += 1

    logger.info(
        "clean 저장소 반영: 신규 %d건, 갱신 %d건, 스킵 %d건 (정책=%s)",
        result["inserted"], result["updated"], result["skipped"], policy,
    )

    return result


def fetch_reviews(sentiment=None, rating=None, rating_min=None,
                  date_from=None, date_to=None, product=None,
                  skin_type=None, unanalyzed_only=False, review_id=None,
                  order_by="review_date", order_dir="asc",
                  limit=None, offset=0, db_path=None):
    """
    조건에 맞는 리뷰를 감정 분석 결과와 함께 조회한다.

    값은 전부 파라미터 바인딩(?)으로 넘겨 SQL 인젝션을 막는다.
    """

    if order_by not in ORDER_COLUMNS:
        raise ValueError(
            f"정렬 기준은 {sorted(ORDER_COLUMNS)} 중 "
            f"하나여야 합니다 (현재: {order_by!r})"
        )

    direction = (
        "DESC" if str(order_dir).lower() in ("desc", "d") else "ASC"
    )

    conditions = []
    params = []

    if review_id is not None:
        conditions.append("r.id = ?")
        params.append(review_id)

    if sentiment:
        conditions.append("a.sentiment = ?")
        params.append(sentiment)

    if rating is not None:
        conditions.append("r.rating = ?")
        params.append(rating)

    if rating_min is not None:
        conditions.append("r.rating >= ?")
        params.append(rating_min)

    if date_from:
        conditions.append("r.review_date >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("r.review_date <= ?")
        params.append(date_to)

    if product:
        conditions.append("r.product_name = ?")
        params.append(product)

    if skin_type:
        conditions.append("r.skin_type = ?")
        params.append(skin_type)

    if unanalyzed_only:
        conditions.append("a.id IS NULL")

    sql = """
        SELECT r.id, r.review_hash, r.product_name, r.review_text,
               r.rating, r.review_date, r.skin_type, r.created_at,
               a.sentiment, a.confidence, a.language,
               a.model, a.analyzed_at
        FROM reviews r
        LEFT JOIN analyses a ON a.review_id = r.id
    """

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)

    sql += f" ORDER BY {ORDER_COLUMNS[order_by]} {direction}, r.id {direction}"

    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])

    with get_connection(db_path) as connection:
        rows = connection.execute(sql, params).fetchall()

    return [dict(row) for row in rows]


def count_reviews(db_path=None, **filters):
    """fetch_reviews 와 같은 조건으로 건수만 센다. 페이지네이션용."""

    filters.pop("limit", None)
    filters.pop("offset", None)

    return len(fetch_reviews(db_path=db_path, **filters))


def save_analysis(review_id, sentiment, confidence,
                  language=None, model=None, db_path=None):
    """감정 분석 결과를 저장한다. 같은 리뷰를 다시 분석하면 덮어쓴다."""

    with get_connection(db_path) as connection:
        connection.execute(
            """
            INSERT INTO analyses
                (review_id, sentiment, confidence, language, model)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(review_id) DO UPDATE SET
                sentiment   = excluded.sentiment,
                confidence  = excluded.confidence,
                language    = excluded.language,
                model       = excluded.model,
                analyzed_at = datetime('now', 'localtime')
            """,
            (review_id, sentiment, float(confidence), language, model),
        )


def save_extraction(scope, review_count, data, model=None, db_path=None):
    """키워드/요약 추출 결과를 저장하고 id 를 반환한다."""

    def as_json(value):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    with get_connection(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO extractions
                (scope, review_count, positive_keywords,
                 negative_keywords, summary, improvements, model)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scope,
                review_count,
                as_json(data.get("positive_keywords")),
                as_json(data.get("negative_keywords")),
                data.get("summary"),
                as_json(data.get("improvements")),
                model,
            ),
        )

        return int(cursor.lastrowid)


def fetch_latest_extraction(db_path=None):
    """가장 최근 추출 결과를 반환한다. 없으면 None."""

    with get_connection(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM extractions ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if row is None:
        return None

    record = dict(row)

    for key in ("positive_keywords", "negative_keywords", "improvements"):

        if record.get(key):
            try:
                record[key] = json.loads(record[key])
            except json.JSONDecodeError:
                pass

    return record


def database_summary(db_path=None):
    """각 테이블의 행 수를 센다. status 확인용."""

    with get_connection(db_path) as connection:

        def count(table):
            return int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )

        return {
            "raw_reviews": count("raw_reviews"),
            "reviews": count("reviews"),
            "analyses": count("analyses"),
            "extractions": count("extractions"),
        }


def fetch_raw_records(db_path=None):
    """raw 저장소에 쌓인 원본을 dict 리스트로 되돌린다. clean 명령용."""

    with get_connection(db_path) as connection:
        rows = connection.execute(
            "SELECT payload FROM raw_reviews ORDER BY id"
        ).fetchall()

    return [json.loads(row["payload"]) for row in rows]


# ============================================================
# 용도별 조회 함수  (전부 main.py 에서만 쓴다)
# ============================================================
#
# [정정] v1 에서는 이 함수들을 "B/C가 쓰는 공개 API" 로 적어뒀는데,
#        실제로 B/C 폴더에서 호출하는 곳은 0곳이다. 그게 맞다.
#
#        C가 여기를 직접 부르면 의존 방향이 뒤집힌다.
#          · C 모듈이 DB 없이는 테스트가 안 된다
#            (지금 민규님은 문자열 리스트만으로 자기 기능을 돌려본다)
#          · "무엇을 분석할지" 를 CLI 와 C가 각각 정하게 된다
#          · analyze --id / --unanalyzed / --limit 해석이 두 군데로 갈린다
#
#        그래서 의존 방향은 A -> C 한 쪽으로만 둔다.
#        아래는 fetch_reviews(인자 13개)를 호출부에서 읽기 쉽게 감싼
#        A 자신의 조회 헬퍼다.
#
# rating / review_date / sentiment / skin_type 은 None 일 수 있다.


def get_unanalyzed_reviews(limit=None, db_path=None):
    """아직 감정 분석이 안 된 리뷰. analyze --unanalyzed 대상."""

    return fetch_reviews(
        unanalyzed_only=True, limit=limit, order_by="id", db_path=db_path
    )


def get_clean_review_by_id(review_id, db_path=None):
    """리뷰 1건을 id 로 가져온다. 없으면 None."""

    rows = fetch_reviews(review_id=review_id, db_path=db_path)

    return rows[0] if rows else None


def get_all_reviews(limit=None, db_path=None):
    """전체 리뷰. analyze --all 대상."""

    return fetch_reviews(limit=limit, order_by="id", db_path=db_path)


def get_reviews_for_extract(sentiment=None, date_from=None, date_to=None,
                            product=None, limit=None, db_path=None):
    """키워드 추출 대상. (명세 4.5)"""

    return fetch_reviews(
        sentiment=sentiment,
        date_from=date_from,
        date_to=date_to,
        product=product,
        limit=limit,
        order_by="id",
        db_path=db_path,
    )


def get_reviews_for_export(sentiment=None, rating_min=None, date_from=None,
                           date_to=None, product=None, db_path=None):
    """내보내기 대상. (명세 4.9)"""

    return fetch_reviews(
        sentiment=sentiment,
        rating_min=rating_min,
        date_from=date_from,
        date_to=date_to,
        product=product,
        order_by="id",
        db_path=db_path,
    )


# save_sentiment_result(단수) 를 뺐다. save_analysis 를 그대로 부르는
# 껍데기였는데 아무도 부르지 않았다. 저장 경로는 아래 복수형 하나다.


def save_sentiment_results(results, model=None, db_path=None):
    """id 를 붙인 results 리스트를 한 번에 저장한다."""

    saved = 0

    for item in results:

        try:
            save_analysis(
                review_id=int(item["id"]),
                sentiment=item["sentiment"],
                confidence=float(item["confidence"]),
                language=item.get("language"),
                model=model,
                db_path=db_path,
            )
            saved += 1

        except (KeyError, TypeError, ValueError) as error:
            logger.warning("결과 저장 실패 %s: %s", item, error)

    return saved
