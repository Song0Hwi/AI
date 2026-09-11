from store import PromptStore

class PromptApp:
    """프로그램의 흐름을 담당하는 클래스"""

    def __init__(self):
        self.running = True

        self.store = PromptStore() 

        count, error = self.store.load_from_json()
        if error is None:
            print(f"[안내] 저장된 프롬프트 {count}개를 불러왔습니다.")

        self.actions = { ... }


        # 번호: (메뉴 이름, 실행할 메서드)
        self.actions = {
            "1": ("프롬프트 추가", self.add_prompt),
            "2": ("프롬프트 목록", self.show_list),
            "3": ("카테고리별 조회", self.show_by_category),
            "4": ("프롬프트 검색", self.search_prompt),
            "5": ("프롬프트 상세 보기", self.show_detail),
            "6": ("즐겨찾기 관리", self.manage_favorite),
            "7": ("즐겨찾기 목록", self.show_favorites),
            "8": ("프롬프트 수정", self.edit_prompt),
            "9": ("프롬프트 삭제", self.delete_prompt),
            "10": ("조회수 Top", self.show_top_viewed),
            "11": ("파일로 저장", self.save_data),
            "12": ("파일에서 불러오기", self.load_data),
            "13": ("Markdown 내보내기", self.export_markdown),
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




    # ---------- 각 기능 ----------

    # ---------- 4.5 프롬프트 추가 ----------

    def add_prompt(self):
        print("\n=== 프롬프트 추가 ===")

        title = self.input_required("제목")
        if title is None:
            return

        content = self.input_multiline("내용")
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
        """한 줄을 입력받는다. 비어 있으면 재입력. 0을 입력하면 None(취소)."""
        while True:
            value = input(f"{label} (취소: 0): ").strip()

            if value == "0":
                print("[안내] 취소했습니다.")
                return None

            if value:
                return value

            print("[안내] 값이 비어 있습니다. 다시 입력해 주세요.")

    @staticmethod
    def input_multiline(label):
        """여러 줄을 입력받는다.
        :q 완료 / :d 마지막 줄 삭제 / :c 전체 삭제 / 첫 줄에서 0 입력 시 취소
        """
        print(f"{label} (완료: :q / 마지막 줄 삭제: :d / 전체 삭제: :c / 취소: 0)")

        lines = []
        while True:
            line = input()
            command = line.strip()

            if command == "0" and not lines:
                print("[안내] 취소했습니다.")
                return None

            if command == ":d":
                if lines:
                    removed = lines.pop()
                    print(f"[삭제] {removed}")
                else:
                    print("[안내] 삭제할 줄이 없습니다.")
                continue

            if command == ":c":
                if lines:
                    lines.clear()
                    print("[삭제] 전체 내용을 비웠습니다. 처음부터 다시 입력해 주세요.")
                else:
                    print("[안내] 삭제할 내용이 없습니다.")
                continue

            if command == ":q":
                if lines:
                    return "\n".join(lines)
                print("[안내] 내용이 비어 있습니다. 다시 입력해 주세요.")
                continue

            lines.append(line)

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

            index = self.ask_index("번호 입력")
            if index is None:
                return

            prompt = self.store.increase_view(index)      # ← 조회수 +1 후 반환

            print()
            print(self.LINE)
            print(f"제목: {prompt['title']}")
            print(f"카테고리: {prompt['category']}")
            print(f"즐겨찾기: {'⭐' if prompt['favorite'] else '없음'}")
            print(f"조회수: {prompt['view_count']}")
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

        # ---------- 보너스 2: 프롬프트 수정 ----------

    def edit_prompt(self):
        print("\n=== 프롬프트 수정 ===")

        if not self.store.prompts:
            print("등록된 프롬프트가 없습니다.")
            return

        index = self.ask_index("수정할 프롬프트 번호")
        if index is None:
            return

        prompt = self.store.get(index)
        print(f"\n현재 제목: {prompt['title']}")
        print(f"현재 카테고리: {prompt['category']}")

        fields = self.select_edit_fields()
        if not fields:
            print("[안내] 수정을 취소했습니다.")
            return

        new_title = None
        new_content = None
        new_category = None

        if "title" in fields:
            new_title = self.input_required("새 제목")
            if new_title is None:
                return

        if "content" in fields:
            new_content = self.input_multiline("새 내용")
            if new_content is None:
                return

        if "category" in fields:
            new_category = self.select_category()
            if new_category is None:
                return

        self.store.update(index, new_title, new_content, new_category)
        print("\n프롬프트가 수정되었습니다!")

    @staticmethod
    def select_edit_fields():
        """수정할 항목을 고른다. 취소나 잘못된 입력이면 빈 리스트."""
        print("\n1) 제목  2) 내용  3) 카테고리  4) 전체")
        choice = input("수정할 항목 (취소: 0): ").strip()

        options = {
            "1": ["title"],
            "2": ["content"],
            "3": ["category"],
            "4": ["title", "content", "category"],
        }
        return options.get(choice, [])

    # ---------- 보너스 2: 프롬프트 삭제 ----------

    def delete_prompt(self):
        print("\n=== 프롬프트 삭제 ===")

        if not self.store.prompts:
            print("등록된 프롬프트가 없습니다.")
            return

        index = self.ask_index("삭제할 프롬프트 번호")
        if index is None:
            return

        prompt = self.store.get(index)
        confirm = input(f"'{prompt['title']}'을(를) 삭제할까요? (y/n): ").strip().lower()

        if confirm != "y":
            print("[안내] 삭제를 취소했습니다.")
            return

        removed = self.store.delete(index)
        print(f"\n'{removed['title']}' 프롬프트를 삭제했습니다.")

    # ---------- 보너스 2: 조회수 Top ----------

    def show_top_viewed(self):
        print("\n=== 조회수 Top ===")

        found = self.store.get_top_viewed()
        if not found:
            print("아직 조회된 프롬프트가 없습니다.")
            return

        for rank, prompt in enumerate(found, start=1):
            star = " ⭐" if prompt["favorite"] else ""
            print(f"{rank}. [{prompt['category']}] {prompt['title']}{star} — {prompt['view_count']}회")

    # ---------- 보너스 1: 저장 / 불러오기 ----------

    def save_data(self):
        print("\n=== 파일로 저장 ===")

        error = self.store.save_to_json()
        if error:
            print(f"[오류] {error}")
            return

        print(f"{len(self.store.prompts)}개의 프롬프트를 "
              f"'{PromptStore.DATA_FILE}'에 저장했습니다.")

    def load_data(self):
        print("\n=== 파일에서 불러오기 ===")

        if self.store.prompts:
            confirm = input("현재 목록이 파일 내용으로 대체됩니다. 계속할까요? (y/n): ")
            if confirm.strip().lower() != "y":
                print("[안내] 불러오기를 취소했습니다.")
                return

        count, error = self.store.load_from_json()
        if error:
            print(f"[오류] {error}")
            return

        print(f"{count}개의 프롬프트를 불러왔습니다.")

    # ---------- 보너스 1: Markdown 내보내기 ----------

    def export_markdown(self):
        print("\n=== Markdown 내보내기 ===")
        print("1) 한 파일로 묶기  2) 카테고리별 파일로 나누기")

        choice = input("선택 (취소: 0): ").strip()

        if choice == "1":
            error = self.store.export_markdown()
            if error:
                print(f"[오류] {error}")
                return
            print("'prompts.md' 파일로 내보냈습니다.")

        elif choice == "2":
            count, error = self.store.export_markdown_by_category()
            if error:
                print(f"[오류] {error}")
                return
            print(f"'exports' 폴더에 {count}개 파일을 만들었습니다.")

        elif choice == "0":
            print("[안내] 취소했습니다.")

        else:
            print("[안내] 1 또는 2를 입력해 주세요.")


    # ---------- 자동 저장 ----------

    def exit_app(self):
        error = self.store.save_to_json()
        if error:
            print(f"\n[경고] {error}")
        else:
            print("\n프롬프트를 저장했습니다.")

        print("프로그램을 종료합니다.")
        self.running = False