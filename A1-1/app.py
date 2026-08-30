from store import PromptStore

class PromptApp:
    """프로그램의 흐름을 담당하는 클래스"""

    def __init__(self):
        self.running = True

        self.store = PromptStore() 


        # 번호: (메뉴 이름, 실행할 메서드)
        self.actions = {
            "1": ("프롬프트 추가", self.add_prompt),
            "2": ("프롬프트 목록", self.show_list),
            "3": ("카테고리별 조회", self.show_by_category),
            "4": ("프롬프트 검색", self.search_prompt),
            "5": ("프롬프트 상세 보기", self.show_detail),
            "6": ("즐겨찾기 관리", self.manage_favorite),
            "7": ("즐겨찾기 목록", self.show_favorites),
            "0": ("종료", self.exit_app),
        }



    # ---------- 실행 루프 ----------


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

    def exit_app(self):
        print("\n프로그램을 종료합니다.")
        self.running = False




    # ---------- 각 기능 (이후 미션에서 구현) ----------

    # ---------- 4.5 프롬프트 추가 ----------

    def add_prompt(self):
        print("\n=== 프롬프트 추가 ===")

        title = self.input_required("제목")
        if title is None:
            return

        content = self.input_required("내용")
        if content is None:
            return

        category = self.select_category()
        if category is None:
            return

        self.store.add(title, content, category)
        print("\n프롬프트가 추가되었습니다!")

    # ---------- 입력 보조 ----------

    @staticmethod
    def input_required(label):
        """비어 있으면 다시 물어본다. 0을 입력하면 None(취소)."""
        while True:
            value = input(f"{label} (취소: 0): ").strip()
            if value == "0":
                print("[안내] 취소했습니다.")
                return None
            if value:
                return value
            print("[안내] 값이 비어 있습니다. 다시 입력해 주세요.")

    def select_category(self, allow_custom=True):
        """카테고리를 고른다. 취소 시 None."""
        print()
        for number, name in enumerate(PromptStore.CATEGORIES, start=1):
            print(f"{number}) {name}")
        if allow_custom:
            print("d) 직접 입력")

        while True:
            choice = input("선택 (취소: 0): ").strip()

            if choice == "0":
                print("[안내] 취소했습니다.")
                return None

            if allow_custom and choice.lower() == "d":
                return self.input_required("카테고리명")

            if choice.isdigit():
                index = int(choice) - 1
                if 0 <= index < len(PromptStore.CATEGORIES):
                    return PromptStore.CATEGORIES[index]

            print("[안내] 목록에 있는 번호를 입력해 주세요.")


 
    # ---------- 4.6 프롬프트 목록 ----------

    def show_list(self):
        print("\n=== 프롬프트 목록 ===")

        if self.store.is_empty():
            print("등록된 프롬프트가 없습니다.")
            return

        self.print_prompts(self.store.get_all())
        print(f"\n총 {self.store.count()}개의 프롬프트")

    # ---------- 출력 보조 ----------

    @staticmethod
    def print_prompts(prompts, show_category=True):
        for number, prompt in enumerate(prompts, start=1):
            star = " ⭐" if prompt["favorite"] else ""
            if show_category:
                print(f"{number}. [{prompt['category']}] {prompt['title']}{star}")
            else:
                print(f"{number}. {prompt['title']}{star}")

# git checkout -b feature/prompt-list  

# git add .

# git commit -m "4.6"

# git checkout main

# git merge feature/prompt-list  

    # ---------- 4.7 카테고리별 조회 ----------

    def show_by_category(self):
        print("\n=== 카테고리별 조회 ===")

        category = self.select_category(allow_custom=False)
        if category is None:
            return

        found = self.store.filter_by_category(category)
        if not found:
            print(f"\n[{category}] 카테고리에 등록된 프롬프트가 없습니다.")
            return

        print(f"\n[{category}] 카테고리 프롬프트:")
        self.print_prompts(found, show_category=False)
        print(f"\n총 {len(found)}개의 프롬프트")

    # ---------- 4.8 프롬프트 검색 ----------

    def search_prompt(self):
        print("\n=== 프롬프트 검색 ===")

        keyword = input("검색어: ").strip()
        if not keyword:
            print("[안내] 검색어를 입력해 주세요.")
            return

        found = self.store.search(keyword)
        if not found:
            print(f"\n'{keyword}'에 대한 검색 결과가 없습니다.")
            return

        print("\n검색 결과:")
        self.print_prompts(found)
        print(f"\n{len(found)}개의 프롬프트를 찾았습니다.")

    # ---------- 4.9 프롬프트 상세 보기 ----------

    LINE = "─" * 28      # 클래스 상단에 추가

    def show_detail(self):
        print("\n=== 프롬프트 상세 보기 ===")

        if not self.store.prompts:
            print("등록된 프롬프트가 없습니다.")
            return

        prompt = self.ask_prompt("번호 입력")
        if prompt is None:
            return

        print()
        print(self.LINE)
        print(f"제목: {prompt['title']}")
        print(f"카테고리: {prompt['category']}")
        print(f"즐겨찾기: {'⭐' if prompt['favorite'] else '없음'}")
        print(self.LINE)
        print("내용:")
        print(prompt["content"])
        print(self.LINE)

    # ---------- 입력 보조 ----------

    def ask_index(self, label):
        """번호를 받아 0-based 인덱스로 반환. 잘못된 입력이면 None."""
        choice = input(f"{label}: ").strip()

        if not choice.isdigit():
            print("[안내] 숫자를 입력해 주세요.")
            return None

        index = int(choice) - 1
        if self.store.get(index) is None:
            print(f"[안내] 1 ~ {len(self.store.prompts)} 사이의 번호를 입력해 주세요.")
            return None

        return index

    def ask_prompt(self, label):
        """번호를 받아 프롬프트 자체를 반환. 실패 시 None."""
        index = self.ask_index(label)
        if index is None:
            return None
        return self.store.get(index)

    # ---------- 4.10 즐겨찾기 관리 ----------

    def manage_favorite(self):
        print("\n=== 즐겨찾기 관리 ===")

        if not self.store.prompts:
            print("등록된 프롬프트가 없습니다.")
            return

        index = self.ask_index("프롬프트 번호 입력")
        if index is None:
            return

        prompt, is_favorite = self.store.toggle_favorite(index)
        state = "추가했습니다" if is_favorite else "해제했습니다"
        print(f"'{prompt['title']}' 프롬프트를 즐겨찾기에 {state}!")

    def show_favorites(self):
        print("\n=== 즐겨찾기 목록 ===")

        found = self.store.get_favorites()
        if not found:
            print("즐겨찾기된 프롬프트가 없습니다.")
            return

        self.print_prompts(found)
        print(f"\n총 {len(found)}개의 즐겨찾기")