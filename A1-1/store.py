import json
import os
import re

class PromptStore:
    """프롬프트 데이터를 보관하고 다루는 클래스"""

    CATEGORIES = ["텍스트 생성", "이미지 생성", "영상 생성", "페르소나", "자동화", "기타"]
    DATA_FILE = "prompts.json"
    REQUIRED_KEYS = ("title", "content", "category", "favorite", "view_count")

    def __init__(self):
        self.prompts = []
        self._load_defaults()
    
    def add(self, title, content, category):
        prompt = {
            "title": title,
            "content": content,
            "category": category,
            "favorite": False,
            "view_count": 0,        # ← 보너스 과제로 추가
        }
        self.prompts.append(prompt)
        return prompt

    def get_all(self):
        return self.prompts

    def count(self):
        return len(self.prompts)

    def is_empty(self):
        return len(self.prompts) == 0

    def filter_by_category(self, category):
        return [p for p in self.prompts if p["category"] == category]

    def search(self, keyword):
        keyword = keyword.lower()
        return [
            p for p in self.prompts
            if keyword in p["title"].lower() or keyword in p["content"].lower()
        ]

    def get(self, index):
        """0-based 인덱스로 하나 반환. 범위 밖이면 None."""
        if 0 <= index < len(self.prompts):
            return self.prompts[index]
        return None

    def get_favorites(self):
        return [p for p in self.prompts if p["favorite"]]

    def toggle_favorite(self, index):
        """즐겨찾기를 뒤집고 (프롬프트, 새 상태)를 반환. 실패 시 (None, None)."""
        prompt = self.get(index)
        if prompt is None:
            return None, None
        prompt["favorite"] = not prompt["favorite"]
        return prompt, prompt["favorite"]


    # ---------- 보너스 2: 수정 / 삭제 ----------

    def update(self, index, title=None, content=None, category=None):
        """전달된 항목만 수정한다. 실패 시 None."""
        prompt = self.get(index)
        if prompt is None:
            return None

        if title is not None:
            prompt["title"] = title
        if content is not None:
            prompt["content"] = content
        if category is not None:
            prompt["category"] = category

        return prompt

    def delete(self, index):
        """삭제한 프롬프트를 반환. 실패 시 None."""
        if self.get(index) is None:
            return None
        return self.prompts.pop(index)

    # ---------- 보너스 2: 조회수 ----------

    def increase_view(self, index):
        prompt = self.get(index)
        if prompt is not None:
            prompt["view_count"] += 1
        return prompt

    def get_top_viewed(self, limit=5):
        viewed = [p for p in self.prompts if p["view_count"] > 0]
        return sorted(viewed, key=lambda p: p["view_count"], reverse=True)[:limit]


    # ---------- 보너스 1: JSON 저장 / 불러오기 ----------


    def save_to_json(self, path=None):
        """현재 프롬프트를 JSON 파일로 저장한다. 실패 시 오류 메시지 반환."""
        path = path or self.DATA_FILE
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.prompts, f, ensure_ascii=False, indent=2)
            return None
        except OSError as e:
            return f"파일을 저장할 수 없습니다: {e}"

    def load_from_json(self, path=None):
        """JSON 파일을 읽어 프롬프트를 교체한다. (불러온 개수, 오류 메시지)."""
        path = path or self.DATA_FILE

        if not os.path.exists(path):
            return 0, f"'{path}' 파일이 없습니다."

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return 0, f"파일을 읽을 수 없습니다: {e}"

        if not isinstance(data, list):
            return 0, "파일 형식이 올바르지 않습니다."

        loaded = [p for p in data if self._is_valid(p)]
        if not loaded:
            return 0, "불러올 수 있는 프롬프트가 없습니다."

        self.prompts = loaded
        return len(loaded), None

    @classmethod
    def _is_valid(cls, prompt):
        return isinstance(prompt, dict) and all(k in prompt for k in cls.REQUIRED_KEYS)

    # ---------- 보너스 1: Markdown 내보내기 ----------

    def export_markdown(self, path="prompts.md"):
        """카테고리별로 묶어 Markdown 파일로 내보낸다. 실패 시 오류 메시지 반환."""
        if not self.prompts:
            return "내보낼 프롬프트가 없습니다."

        lines = ["# 프롬프트 모음", "", f"총 {len(self.prompts)}개", ""]

        for category in self._used_categories():
            lines.append(f"## {category}")
            lines.append("")

            for prompt in self.filter_by_category(category):
                star = " ⭐" if prompt["favorite"] else ""
                lines.append(f"### {prompt['title']}{star}")
                lines.append("")
                lines.append("```")
                lines.append(prompt["content"])
                lines.append("```")
                lines.append("")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return None
        except OSError as e:
            return f"파일을 저장할 수 없습니다: {e}"

    def _used_categories(self):
        """실제로 사용 중인 카테고리를 정의 순서대로, 사용자 정의는 뒤에 붙여 반환."""
        used = {p["category"] for p in self.prompts}
        ordered = [c for c in self.CATEGORIES if c in used]
        extra = sorted(used - set(self.CATEGORIES))
        return ordered + extra

    # ---------- 보너스 1: category별 Markdown 내보내기 ----------
    def export_markdown_by_category(self, folder="exports"):
        """카테고리마다 별도 Markdown 파일로 내보낸다. (파일 수, 오류 메시지)."""
        if not self.prompts:
            return 0, "내보낼 프롬프트가 없습니다."

        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            return 0, f"폴더를 만들 수 없습니다: {e}"

        count = 0
        for category in self._used_categories():
            lines = [f"# {category}", ""]

            for prompt in self.filter_by_category(category):
                star = " ⭐" if prompt["favorite"] else ""
                lines.append(f"## {prompt['title']}{star}")
                lines.append("")
                lines.append("```")
                lines.append(prompt["content"])
                lines.append("```")
                lines.append("")

            path = os.path.join(folder, f"{self._safe_filename(category)}.md")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                count += 1
            except OSError as e:
                return count, f"'{category}' 저장 실패: {e}"

        return count, None

    @staticmethod
    def _safe_filename(name):
        """파일명에 쓸 수 없는 문자를 _로 바꾼다."""
        return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "untitled"