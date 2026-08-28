

class PromptApp:
    """프로그램의 흐름을 담당하는 클래스"""

    def __init__(self):
        self.running = True
        # 번호: (메뉴 이름, 실행할 메서드)
        self.actions = {
            "1": ("프롬프트 추가", self.add_prompt),
            "2": ("프롬프트 목록", self.show_list),
            "3": ("카테고리별 조회", self.show_by_category),
            "4": ("프롬프트 검색", self.search_prompt),
            "5": ("프롬프트 상세 보기", self.show_detail),
            "6": ("즐겨찾기 등록/해제", self.toggle_favorite),
            "7": ("즐겨찾기 목록", self.show_favorites),
            "0": ("종료", self.exit_app),
        }



# ===실행 루프===

    def run(self):
        while self.running:
            self.show_menu()
            choice = input("번호를 선택하세요 > ").strip()
            self.handle_choice(choice)

    def show_menu(self):
        print()
        print("=" * 36)
        print("        프롬프트 관리 프로그램")
        print("=" * 36)
        for number, (label, _) in self.actions.items():
            print(f"  {number}. {label}")
        print("=" * 36)

    def handle_choice(self, choice):
        action = self.actions.get(choice)
        if action is None:
            print("\n[안내] 잘못된 번호입니다. 메뉴에 있는 번호를 입력해 주세요.")
            return
        label, handler = action
        handler()

# === 각 기능 ===