"""
Firebase Firestore 연동 및 데이터 영속성 서비스 (firebase_service.py)
- Firestore Database의 'data' 및 'conversations' 컬렉션을 관리합니다.
- 환경변수 FIREBASE_SERVICE_ACCOUNT_JSON (파일 경로 또는 JSON 문자열)을 통해 인증합니다.
- 초기 구동 시 Firestore에 시계열 데이터(151개 포인트)가 없으면 자동으로 배치 적재(Seed)합니다.
"""
import os
import csv
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

import firebase_admin
from firebase_admin import credentials, firestore

from config import settings, BASE_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class FirebaseService:
    def __init__(self):
        self.db = None
        self.connected = False
        self.project_id = "local-fallback"
        self.backup_path = BASE_DIR / "data" / "local_store_backup.json"
        self.csv_seed_path = BASE_DIR / "data" / "119_timeseries.csv"
        self._data_cache: Dict[str, Dict[str, Any]] = {}
        self._conv_cache: Dict[str, Dict[str, Any]] = {}
        self._init_firestore()
        self._load_or_seed()

    def _init_firestore(self):
        raw_cfg = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        if not raw_cfg:
            print("[FirebaseService] FIREBASE_SERVICE_ACCOUNT_JSON 미설정 -> 로컬 백업 모드로 동작")
            return

        try:
            if not firebase_admin._apps:
                if raw_cfg.startswith("{"):
                    cred_dict = json.loads(raw_cfg)
                    cred = credentials.Certificate(cred_dict)
                    self.project_id = cred_dict.get("project_id", "firebase-project")
                else:
                    key_path = Path(raw_cfg)
                    if not key_path.is_absolute():
                        key_path = (BASE_DIR / raw_cfg).resolve()
                    if not key_path.exists():
                        raise FileNotFoundError(f"서비스 계정 키 파일을 찾을 수 없습니다: {key_path}")
                    with open(key_path, "r", encoding="utf-8") as f:
                        cred_dict = json.load(f)
                        self.project_id = cred_dict.get("project_id", "firebase-project")
                    cred = credentials.Certificate(str(key_path))
                firebase_admin.initialize_app(cred)

            self.db = firestore.client()
            self.connected = True
            print(f"[FirebaseService] Firestore 연결 성공 (project_id={self.project_id})")
        except Exception as e:
            print(f"[FirebaseService] Firestore 초기화 실패, 로컬 스토리지 폴백 활성화: {e}")
            self.connected = False
            self.db = None

    def _read_seed_csv(self) -> List[Dict[str, Any]]:
        items = []
        if not self.csv_seed_path.exists():
            return items
        with open(self.csv_seed_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                doc_id = f"ts_{row['date'].replace('-', '')}_{idx:03d}"
                ts = now_iso()
                items.append({
                    "id": doc_id,
                    "date": row["date"].strip(),
                    "value": float(row["value"]),
                    "memo": row.get("memo", "").strip(),
                    "created_at": ts,
                    "updated_at": ts,
                })
        return items

    def _default_conversations(self) -> List[Dict[str, Any]]:
        ts = now_iso()
        return [
            {
                "id": "conv_sample_001",
                "title": "2022~2025 전국 119 신고접수 추세 및 피크 시기 분석",
                "messages": [
                    {
                        "role": "user",
                        "content": "전체 119 신고접수 데이터의 기간과 평균, 그리고 가장 신고가 많았던 시기가 언제인지 알려줘.",
                        "timestamp": ts,
                    },
                    {
                        "role": "assistant",
                        "content": (
                            "현재 저장된 **전국 119 신고접수 시계열 데이터(2022-01 ~ 2025-09, 총 151개 주간 포인트)** 분석 결과입니다.\n\n"
                            "1. **전체 요약 지표**\n"
                            "   - **분석 기간**: `2022-01 ~ 2025-09` (총 151주)\n"
                            "   - **주간 평균 접수**: 약 **185,419건** (전체 누적 약 2,799만 건)\n"
                            "   - **최대 접수 시기**: **2024-08-12 주간 (338,467건)** — 여름철 폭염·온열질환 및 집중호우 출동이 겹치며 최고치를 기록했습니다.\n"
                            "   - **최소 접수 시기**: **2022-06-13 주간 (16,323건)**\n\n"
                            "2. **핵심 트렌드 및 인사이트**\n"
                            "   - 매년 **7~8월 여름철**에 주간 28만~33만 건으로 뚜렷한 계절적 피크가 발생하며, 지역별로는 **경기도(약 20%)와 서울특별시(약 16%)**가 전체 신고의 약 36%를 차지합니다."
                        ),
                        "timestamp": ts,
                        "tool_calls": [
                            {"tool": "get_data_summary", "reason": "전체 기간·평균·최대/최소 시점 확인"},
                            {"tool": "get_advanced_statistics", "reason": "계절별 피크 및 지역 비중 확인"},
                        ],
                    },
                ],
                "message_count": 2,
                "created_at": ts,
                "updated_at": ts,
            },
            {
                "id": "conv_sample_002",
                "title": "여름철 현장도착 소요시간 및 대응 전략 문의",
                "messages": [
                    {
                        "role": "user",
                        "content": "신고가 급증하는 여름철에는 현장도착 시간이 어떻게 변해? 대응 방안도 추천해줘.",
                        "timestamp": ts,
                    },
                    {
                        "role": "assistant",
                        "content": (
                            "시계열 데이터의 메모 및 상세 지표를 분석한 결과, **신고량이 급증하는 여름철(7~8월)과 연말·연초 폭설기에는 평균 현장도착 시간이 평소(8.5~9.5분) 대비 11.0~12.8분으로 약 20~30% 지연**되는 패턴이 확인됩니다.\n\n"
                            "- **관찰 근거**: 최고치를 기록한 `2024-07-29`(334,839건) 주간에는 평균 현장도착 시간이 **12.8분**, `2024-08-05`(314,096건)에는 **12.2분**으로 상승했습니다.\n"
                            "- **권장 대응 액션**:\n"
                            "  1. **피크 시간대(09시~16시) 구급차 탄력 배치**: 신고 집중 시간대인 오전 9시~오후 4시 사이 경기도·서울 외곽 및 비도시 지역의 펌뷸런스(Pumbulance) 동시 출동 체계를 강화해야 합니다.\n"
                            "  2. **비응급 신고 사전 필터링**: 폭염기 단순 문의·비응급 신고를 119 안내센터에서 분산 처리하여 긴급 출동 골든타임을 확보하는 것이 효과적입니다."
                        ),
                        "timestamp": ts,
                        "tool_calls": [
                            {"tool": "search_timeseries_data", "reason": "여름철(7~8월) 고점 구간 데이터 및 현장도착 시간 조회"}
                        ],
                    },
                ],
                "message_count": 2,
                "created_at": ts,
                "updated_at": ts,
            },
        ]

    def _save_local_backup(self):
        try:
            self.backup_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": now_iso(),
                "data": list(self._data_cache.values()),
                "conversations": list(self._conv_cache.values()),
            }
            with open(self.backup_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[FirebaseService] 로컬 백업 저장 경고: {e}")

    def _load_or_seed(self):
        # 1. Firestore에서 기존 데이터 로드 시도
        if self.connected and self.db is not None:
            try:
                docs = list(self.db.collection("data").stream())
                if len(docs) >= 100:
                    for d in docs:
                        item = d.to_dict()
                        item["id"] = d.id
                        self._data_cache[d.id] = item
                    print(f"[FirebaseService] Firestore 'data' 컬렉션에서 {len(docs)}개 데이터 로드 완료")
                else:
                    # 시드 데이터 적재 (Batch write)
                    seed_items = self._read_seed_csv()
                    print(f"[FirebaseService] Firestore 'data' 초기 시딩 시작 ({len(seed_items)}개 포인트)...")
                    batch = self.db.batch()
                    count_in_batch = 0
                    for item in seed_items:
                        doc_ref = self.db.collection("data").document(item["id"])
                        batch.set(doc_ref, item)
                        self._data_cache[item["id"]] = item
                        count_in_batch += 1
                        if count_in_batch >= 400:
                            batch.commit()
                            batch = self.db.batch()
                            count_in_batch = 0
                    if count_in_batch > 0:
                        batch.commit()
                    print(f"[FirebaseService] Firestore 'data' {len(seed_items)}개 적재 완료!")

                # Conversations 로드 또는 초기 시딩
                conv_docs = list(self.db.collection("conversations").stream())
                if conv_docs:
                    for cd in conv_docs:
                        c_item = cd.to_dict()
                        c_item["id"] = cd.id
                        self._conv_cache[cd.id] = c_item
                    print(f"[FirebaseService] Firestore 'conversations'에서 {len(conv_docs)}개 대화 로드 완료")
                else:
                    default_convs = self._default_conversations()
                    for c_item in default_convs:
                        self.db.collection("conversations").document(c_item["id"]).set(c_item)
                        self._conv_cache[c_item["id"]] = c_item
                    print(f"[FirebaseService] Firestore 'conversations' 샘플 대화 {len(default_convs)}개 시딩 완료")

                self._save_local_backup()
                return
            except Exception as e:
                print(f"[FirebaseService] Firestore 초기 로드/시딩 중 오류 발생 -> 로컬 백업으로 전환: {e}")

        # 2. 로컬 백업 또는 CSV에서 로드
        if self.backup_path.exists():
            try:
                with open(self.backup_path, "r", encoding="utf-8") as f:
                    backup = json.load(f)
                for item in backup.get("data", []):
                    self._data_cache[item["id"]] = item
                for c_item in backup.get("conversations", []):
                    self._conv_cache[c_item["id"]] = c_item
                if len(self._data_cache) >= 100:
                    return
            except Exception:
                pass

        for item in self._read_seed_csv():
            self._data_cache[item["id"]] = item
        for c_item in self._default_conversations():
            self._conv_cache[c_item["id"]] = c_item
        self._save_local_backup()

    # ==========================================================
    # Data CRUD (Collection: 'data')
    # ==========================================================
    def list_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        search: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        items = list(self._data_cache.values())
        if start_date:
            items = [x for x in items if x["date"] >= start_date]
        if end_date:
            items = [x for x in items if x["date"] <= end_date]
        if search:
            q = search.strip().lower()
            items = [
                x for x in items
                if q in x["date"].lower() or q in str(x.get("memo", "")).lower() or q in str(int(x["value"]))
            ]
        # 날짜 오름차순 정렬
        items.sort(key=lambda x: x["date"])
        if limit and limit > 0:
            items = items[-limit:]
        return items

    def get_data_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        return self._data_cache.get(doc_id)

    def create_data(self, date: str, value: float, memo: str) -> Dict[str, Any]:
        ts = now_iso()
        doc_id = f"ts_{date.replace('-', '')}_{uuid.uuid4().hex[:6]}"
        item = {
            "id": doc_id,
            "date": date,
            "value": float(value),
            "memo": memo.strip(),
            "created_at": ts,
            "updated_at": ts,
        }
        if self.connected and self.db is not None:
            self.db.collection("data").document(doc_id).set(item)
        self._data_cache[doc_id] = item
        self._save_local_backup()
        return item

    def update_data(
        self,
        doc_id: str,
        date: Optional[str] = None,
        value: Optional[float] = None,
        memo: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self._data_cache.get(doc_id)
        if not existing:
            return None

        updated = dict(existing)
        if date is not None:
            updated["date"] = date
        if value is not None:
            updated["value"] = float(value)
        if memo is not None:
            updated["memo"] = memo.strip()
        updated["updated_at"] = now_iso()

        if self.connected and self.db is not None:
            self.db.collection("data").document(doc_id).set(updated, merge=True)
        self._data_cache[doc_id] = updated
        self._save_local_backup()
        return updated

    def delete_data(self, doc_id: str) -> bool:
        if doc_id not in self._data_cache:
            return False
        if self.connected and self.db is not None:
            self.db.collection("data").document(doc_id).delete()
        del self._data_cache[doc_id]
        self._save_local_backup()
        return True

    # ==========================================================
    # Conversations CRUD (Collection: 'conversations')
    # ==========================================================
    def list_conversations(self) -> List[Dict[str, Any]]:
        convs = list(self._conv_cache.values())
        convs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return convs

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        return self._conv_cache.get(conv_id)

    def save_conversation(
        self,
        messages: List[Dict[str, Any]],
        title: Optional[str] = None,
        conv_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        ts = now_iso()
        if conv_id and conv_id in self._conv_cache:
            existing = self._conv_cache[conv_id]
            created_at = existing.get("created_at", ts)
            final_title = title or existing.get("title") or "AI 데이터 분석 대화"
        else:
            conv_id = conv_id or f"conv_{uuid.uuid4().hex[:10]}"
            created_at = ts
            if not title:
                first_user_msg = next(
                    (m.get("content", "") for m in messages if m.get("role") == "user"),
                    "새 데이터 분석 대화",
                )
                final_title = first_user_msg[:36] + ("..." if len(first_user_msg) > 36 else "")
            else:
                final_title = title.strip()

        norm_messages = []
        for m in messages:
            norm_messages.append({
                "role": m.get("role", "user"),
                "content": m.get("content", ""),
                "timestamp": m.get("timestamp") or ts,
                "tool_calls": m.get("tool_calls") or [],
            })

        conv_doc = {
            "id": conv_id,
            "title": final_title,
            "messages": norm_messages,
            "message_count": len(norm_messages),
            "created_at": created_at,
            "updated_at": ts,
        }

        if self.connected and self.db is not None:
            self.db.collection("conversations").document(conv_id).set(conv_doc)
        self._conv_cache[conv_id] = conv_doc
        self._save_local_backup()
        return conv_doc

    def delete_conversation(self, conv_id: str) -> bool:
        if conv_id not in self._conv_cache:
            return False
        if self.connected and self.db is not None:
            self.db.collection("conversations").document(conv_id).delete()
        del self._conv_cache[conv_id]
        self._save_local_backup()
        return True


firebase_service = FirebaseService()
