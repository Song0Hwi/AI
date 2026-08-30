class PromptStore:
    """프롬프트 데이터를 보관하고 다루는 클래스"""

    CATEGORIES = ["텍스트 생성", "이미지 생성", "영상 생성", "페르소나", "자동화", "기타"]

    def __init__(self):
        self.prompts = []

    def add(self, title, content, category):
        prompt = {
            "title": title,
            "content": content,
            "category": category,
            "favorite": False,
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