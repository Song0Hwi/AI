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