import flet as ft
import json
import threading
from pathlib import Path
import sys
import platform

sys.path.append(str(Path(__file__).parent))
from smart_rag import SmartRAG

# Попытка импорта процессора документов
try:
    from document_processor import add_document, list_documents
except ImportError:
    add_document = None
    list_documents = None

# ==========================================
# ЦВЕТА И КОНСТАНТЫ
# ==========================================
THEME = {
    "bg_main": "#1a1f2e",
    "bg_sidebar": "#0f1419",
    "bg_input": "#252b3b",
    "bg_bubble_user": "#2563eb",
    "bg_bubble_ai": "#252b3b",
    "text_primary": "#e2e8f0",
    "text_secondary": "#64748b",
    "accent": "#f59e0b",
    "border": "#334155",
    "status_ready": "#10b981",
    "status_busy": "#f59e0b",
}

APP_NAME = "Aviation RAG-System"
APP_VERSION = "1.0.0"
CHATS_FILE = "chats_history.json"
ASSETS_DIR = Path("assets")

AVAILABLE_MODELS = {
    "Qwen 2.5 (14B)": "qwen2.5:14b",
    "Qwen 2.5 (7B)": "qwen2.5:7b",
    "Llama 3.1 (8B)": "llama3.1:8b",
    "Gemma 2 (9B)": "gemma2:9b",
    "Mistral (7B)": "mistral:7b",
}
DEFAULT_MODEL_DISPLAY = "Qwen 2.5 (14B)"


# ==========================================
# ЗАГРУЗКА ASSETS
# ==========================================
def load_assets():
    """Загружает все изображения из папки assets"""
    assets = {}
    
    # Логотип
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        assets["logo"] = str(logo_path)
    
    # Аватарки
    for name in ["assistant", "user"]:
        path = ASSETS_DIR / "avatars" / f"{name}.png"
        if path.exists():
            assets[name] = str(path)
    
    # Иконки
    for name in ["clear", "new_chat", "send", "settings"]:
        path = ASSETS_DIR / "icons" / f"{name}.png"
        if path.exists():
            assets[name] = str(path)
    
    # Фон
    bg_path = ASSETS_DIR / "background.png"
    if bg_path.exists():
        assets["background"] = str(bg_path)
    
    # Иконка приложения
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        assets["icon"] = str(icon_path)
    
    return assets


# ==========================================
# CHAT MANAGER
# ==========================================
class ChatManager:
    def __init__(self, filename: str = CHATS_FILE):
        self.filename = filename
        self.chats = {}
        self.current_chat_id = None
        self.load()
    
    def load(self):
        if Path(self.filename).exists():
            with open(self.filename, 'r', encoding='utf-8') as f:
                self.chats = json.load(f)
        if not self.chats:
            self.create_new_chat()
        else:
            self.current_chat_id = list(self.chats.keys())[-1]
    
    def save(self):
        with open(self.filename, 'w', encoding='utf-8') as f:
            json.dump(self.chats, f, ensure_ascii=False, indent=2)
    
    def create_new_chat(self, name: str = "Новый чат"):
        import uuid
        chat_id = str(uuid.uuid4())[:8]
        self.chats[chat_id] = {"name": name, "messages": []}
        self.current_chat_id = chat_id
        self.save()
        return chat_id
    
    def delete_chat(self, chat_id: str):
        if chat_id in self.chats:
            del self.chats[chat_id]
            if self.current_chat_id == chat_id:
                self.current_chat_id = list(self.chats.keys())[0] if self.chats else None
                if not self.current_chat_id:
                    self.create_new_chat()
            self.save()
    
    def rename_chat(self, chat_id: str, new_name: str):
        if chat_id in self.chats:
            self.chats[chat_id]["name"] = new_name
            self.save()
    
    def get_current_chat(self):
        if self.current_chat_id and self.current_chat_id in self.chats:
            return self.chats[self.current_chat_id]
        return None
    
    def add_message(self, role: str, content: str, attachments=None, sources=None):
        chat = self.get_current_chat()
        if chat:
            chat["messages"].append({
                "role": role, 
                "content": content, 
                "attachments": attachments or [],
                "sources": sources or []
            })
            self.save()
    
    def switch_chat(self, chat_id: str):
        if chat_id in self.chats:
            self.current_chat_id = chat_id


# ==========================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# ==========================================
class AviationRAGApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.theme = THEME
        self.assets = load_assets()
        self.current_model_display = DEFAULT_MODEL_DISPLAY
        self.current_model_ollama = AVAILABLE_MODELS[self.current_model_display]
        
        self.chat_manager = ChatManager()
        self.rag_system = None
        self.is_processing = False
        
        self.chat_list_controls = {}
        self.file_picker = None
        
        self._setup_page()
        self._build_ui()
        self._load_current_chat()
    
    def _setup_page(self):
        self.page.title = f"{APP_NAME} v{APP_VERSION}"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = self.theme["bg_main"]
        self.page.window.width = 1400
        self.page.window.height = 900
        self.page.window.min_width = 1100
        self.page.window.min_height = 700
        self.page.padding = 0
        self.page.fonts = {
            "main": "SF Pro Display" if platform.system() == "Darwin" else "Segoe UI",
        }
        self.page.padding = 0
        self.page.spacing = 0
        
        # Устанавливаем иконку приложения если есть
        if "icon" in self.assets:
            self.page.window.icon = self.assets["icon"]

    def _build_ui(self):
        self.chat_list_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=4)
        
        btn_accent_style = ft.ButtonStyle(
            bgcolor=self.theme["accent"], color="#ffffff", shape=ft.RoundedRectangleBorder(radius=10)
        )
        btn_text_style = ft.ButtonStyle(color=self.theme["text_primary"])
        
        # Логотип в сайдбаре
        logo_control = None
        if "logo" in self.assets:
            logo_control = ft.Image(src=self.assets["logo"], height=60, width=60)
        
        # --- САЙДБАР ---
        self.sidebar = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        logo_control if logo_control else ft.Text("✈️", size=40),
                        ft.Text("Aviation RAG", size=18, weight=ft.FontWeight.BOLD, color=self.theme["text_primary"]),
                        ft.Text("AI Engine v1.0", size=11, color=self.theme["text_secondary"]),
                    ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.padding.all(16),
                ),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.ElevatedButton(
                    "＋ Новый чат", 
                    icon=self.assets.get("new_chat", ft.Icons.ADD),
                    on_click=self._handle_new_chat, 
                    style=btn_accent_style, 
                    width=float("inf")
                ),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.Container(content=self.chat_list_column, expand=True),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.TextButton(
                    "⚙ Настройки", 
                    icon=self.assets.get("settings", ft.Icons.SETTINGS),
                    on_click=self._show_settings, 
                    style=btn_text_style, 
                    width=float("inf")
                ),
            ], spacing=0),
            width=280,
            bgcolor=self.theme["bg_sidebar"],
        )
        
        # --- ВЕРХНЯЯ ПАНЕЛЬ ---
        self.status_text = ft.Text("● Готов", size=13, weight=ft.FontWeight.BOLD, color=self.theme["status_ready"])
        self.model_label = ft.Text(f"{self.current_model_display}  •  PRL-27СМ RAG", size=14, weight=ft.FontWeight.BOLD, color=self.theme["text_secondary"])
        
        self.header = ft.Container(
            content=ft.Row([self.model_label, ft.Container(expand=True), self.status_text]),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
        )
        
        # --- ОБЛАСТЬ СООБЩЕНИЙ ---
        self.messages_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12)
        
        self.welcome = ft.Container(
            content=ft.Column([
                ft.Text("✈️", size=60),
                ft.Text("Чем могу помочь?", size=32, weight=ft.FontWeight.BOLD, color=self.theme["text_primary"]),
                ft.Text("Задайте вопрос по документации ПРЛ-27СМ", size=15, color=self.theme["text_secondary"]),
                ft.Container(height=30),
                ft.Row([
                    ft.ElevatedButton("Как включить излучение шкафа 276ГГ02?", on_click=lambda e: self._send_example(e.control.text), width=300, height=55),
                    ft.ElevatedButton("Что такое сигнал PPS?", on_click=lambda e: self._send_example(e.control.text), width=300, height=55),
                ], wrap=True, spacing=10, alignment=ft.MainAxisAlignment.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10),
            expand=True,
            alignment=ft.alignment.center,
        )
        
        self.chat_stack = ft.Stack([self.welcome, self.messages_column], expand=True)
        
        self.chat_area = ft.Container(
            content=ft.Column([self.header, self.chat_stack], spacing=0),
            expand=True,
        )
        
        # --- ПОЛЕ ВВОДА ---
        self.input_field = ft.TextField(
            hint_text="Message RAG Assistant...",
            multiline=True,
            min_lines=1,
            max_lines=5,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            border_color=self.theme["border"],
            focused_border_color=self.theme["accent"],
            text_style=ft.TextStyle(size=15, font_family="main"),
            on_submit=self._handle_send,
            expand=True,
        )
        
        # File picker для загрузки файлов
        self.file_picker = ft.FilePicker(
            on_result=self._on_file_pick_result,
            dialog_title="Выберите документ для загрузки",
            allowed_extensions=["pdf", "docx", "txt", "md", "csv", "xlsx"],
            allow_multiple=False
        )
        
        self.page.overlay.append(self.file_picker)
        
        self.input_area = ft.Container(
            content=ft.Row([
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE_OUTLINE, 
                    tooltip="Прикрепить документ", 
                    on_click=lambda e: self.file_picker.pick_files(),
                    style=ft.ButtonStyle(color=self.theme["accent"]),
                ),
                self.input_field,
                ft.IconButton(
                    icon=self.assets.get("send", ft.Icons.SEND), 
                    tooltip="Отправить", 
                    on_click=self._handle_send, 
                    style=ft.ButtonStyle(bgcolor=self.theme["accent"], color="#ffffff")
                ),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.END),
            padding=ft.padding.all(20),
            bgcolor=self.theme["bg_main"],
        )
        
        # --- СБОРКА СТРАНИЦЫ ---
        self.page.add(
            ft.Row([
                self.sidebar,
                ft.VerticalDivider(width=1, color=self.theme["border"]),
                ft.Column([self.chat_area, ft.Divider(height=1, color=self.theme["border"]), self.input_area], spacing=0, expand=True),
            ], expand=True, spacing=0)
        )

    def _on_file_pick_result(self, e: ft.FilePickerResultEvent):
        """Обработчик результата выбора файла"""
        if e.files:
            file_path = e.files[0].path
            self.status_text.value = "● Обрабатываю документ..."
            self.status_text.color = self.theme["status_busy"]
            self.page.update()
            threading.Thread(target=self._process_document, args=(file_path,), daemon=True).start()

    def _update_chat_list(self):
        self.chat_list_column.controls.clear()
        self.chat_list_controls.clear()
        
        for chat_id, chat_data in reversed(list(self.chat_manager.chats.items())):
            is_current = chat_id == self.chat_manager.current_chat_id
            name = chat_data["name"][:28] + ("..." if len(chat_data["name"]) > 28 else "")
            
            btn = ft.ListTile(
                title=ft.Text(name, size=13, color="#ffffff" if is_current else self.theme["text_primary"]),
                bgcolor=self.theme["accent"] if is_current else None,
                shape=ft.RoundedRectangleBorder(radius=8),
                on_click=lambda e, cid=chat_id: self._switch_chat(cid),
            )
            self.chat_list_column.controls.append(btn)
            self.chat_list_controls[chat_id] = btn
        self.page.update()

    def _handle_new_chat(self, e):
        self.chat_manager.create_new_chat()
        self._update_chat_list()
        self._load_current_chat()

    def _switch_chat(self, chat_id):
        self.chat_manager.switch_chat(chat_id)
        self._update_chat_list()
        self._load_current_chat()

    def _load_current_chat(self):
        chat = self.chat_manager.get_current_chat()
        self.messages_column.controls.clear()
        
        if chat and chat["messages"]:
            self.welcome.visible = False
            for msg in chat["messages"]:
                self._add_message_to_ui(
                    msg["role"], 
                    msg["content"], 
                    msg.get("attachments") or [],
                    msg.get("sources") or []
                )
        else:
            self.welcome.visible = True
        self.page.update()

    def _add_message_to_ui(self, role, content, attachments=None, sources=None):
        if role == "user":
            attach_controls = []
            if attachments:
                for name in attachments:
                    attach_controls.append(
                        ft.Chip(
                            label=ft.Text(name, size=12, color="#dbeafe"),
                            bgcolor="#1e3a8a",
                            checkmark_color="#dbeafe",
                            padding=6,
                        )
                    )
            
            bubble = ft.Container(
                content=ft.Column(attach_controls + [ft.Text(content, size=15, color="#ffffff", selectable=True)], spacing=8),
                bgcolor=self.theme["bg_bubble_user"],
                padding=16,
                border_radius=20,
            )
            row = ft.Row([
                ft.Container(expand=True), 
                ft.Text("👤", size=28) if "user" not in self.assets else ft.Image(src=self.assets["user"], width=40, height=40),
                bubble
            ], vertical_alignment=ft.CrossAxisAlignment.START)
        else:
            # Markdown с поддержкой копирования кода
            md = ft.Markdown(
                value=content,
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme="vs-dark",
            )
            
            # Блок с источниками если есть
            source_controls = []
            if sources:
                source_text = ", ".join(sources[:3])  # Показываем первые 3 источника
                if len(sources) > 3:
                    source_text += f" и еще {len(sources) - 3}"
                source_controls.append(
                    ft.Container(
                        content=ft.Text(f"📎 Источники: {source_text}", size=11, color=self.theme["text_secondary"]),
                        padding=ft.padding.only(top=8),
                    )
                )
            
            bubble = ft.Container(
                content=ft.Column([md] + source_controls, spacing=4),
                bgcolor=self.theme["bg_bubble_ai"],
                padding=16,
                border_radius=20,
                expand=True
            )
            row = ft.Row([
                ft.Text("🤖", size=28) if "assistant" not in self.assets else ft.Image(src=self.assets["assistant"], width=40, height=40),
                bubble
            ], vertical_alignment=ft.CrossAxisAlignment.START)
        
        self.messages_column.controls.append(row)
        self.welcome.visible = False
        self.page.update()
        # Прокрутка вниз
        self.messages_column.scroll_to(offset=-1, duration=300)

    def _handle_send(self, e):
        text = self.input_field.value.strip()
        if not text or self.is_processing:
            return
        
        self.input_field.value = ""
        
        chat = self.chat_manager.get_current_chat()
        if chat and chat["name"] == "Новый чат" and len(chat["messages"]) == 0:
            new_name = text[:30] + ("..." if len(text) > 30 else "")
            self.chat_manager.rename_chat(self.chat_manager.current_chat_id, new_name)
            self._update_chat_list()
        
        self._add_message_to_ui("user", text)
        self.chat_manager.add_message("user", text)
        
        self.is_processing = True
        self.status_text.value = "● Думаю..."
        self.status_text.color = self.theme["status_busy"]
        self.page.update()
        
        threading.Thread(target=self._process, args=(text,), daemon=True).start()

    def _send_example(self, text):
        self.input_field.value = text
        self._handle_send(None)

    def _handle_attach(self, e):
        # Теперь вызывается через file_picker.pick_files()
        pass

    def _process_document(self, file_path: str):
        try:
            if add_document:
                chat_id = self.chat_manager.current_chat_id or "global"
                info = add_document(file_path, chat_id=chat_id)
                self.page.run_thread(self._on_document_ready, info)
            else:
                self.page.run_thread(self._on_document_ready, {"error": "Модуль document_processor не найден"})
        except Exception as e:
            import traceback
            print(f"[ERROR] {e}\n{traceback.format_exc()}")
            self.page.run_thread(self._on_document_ready, {"error": str(e)})

    def _on_document_ready(self, info):
        if "error" in info:
            self.page.show_snack_bar(ft.SnackBar(ft.Text(f"❌ Ошибка: {info['error']}"), bgcolor="#ef4444"))
        else:
            self.page.show_snack_bar(ft.SnackBar(ft.Text(f"✅ Загружено: {info['filename']} ({info['chunks']} фр.)"), bgcolor="#10b981"))
        
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self.page.update()

    def _process(self, user_input: str):
        try:
            if self.rag_system is None:
                self.rag_system = SmartRAG(model_name=self.current_model_ollama)
            
            # Получаем ответ с источниками
            response = self.rag_system.query(user_input, chat_id=self.chat_manager.current_chat_id)
            clean = response.replace("[С поиском]:\n", "").replace("[Без поиска]: ", "")
            
            # Извлекаем источники из ответа (если они есть в формате [Источник: filename])
            sources = []
            import re
            source_matches = re.findall(r'\[Источник:\s*([^\]]+)\]', response)
            sources = source_matches
            
            # Очищаем ответ от меток источников
            clean = re.sub(r'\n?\[Источник:[^\]]+\]', '', clean).strip()
            
            self.page.run_thread(self._on_response_ready, clean, sources)
        except Exception as e:
            import traceback
            print(f"[ERROR] {e}\n{traceback.format_exc()}")
            self.page.run_thread(self._on_response_ready, f"Ошибка: {e}", [])

    def _on_response_ready(self, response, sources):
        self._add_message_to_ui("assistant", response, sources=sources)
        self.chat_manager.add_message("assistant", response, sources=sources)
        self.is_processing = False
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self.page.update()

    def _show_settings(self, e):
        model_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(k) for k in AVAILABLE_MODELS.keys()],
            value=self.current_model_display,
            width=300,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
        )
        status_lbl = ft.Text(f"Активная: {self.current_model_display}", color=self.theme["status_ready"], size=12)
        
        def apply_model(e):
            chosen = model_dropdown.value
            if chosen and chosen in AVAILABLE_MODELS:
                self.current_model_display = chosen
                self.current_model_ollama = AVAILABLE_MODELS[chosen]
                self.model_label.value = f"{chosen}  •  PRL-27СМ RAG"
                self.rag_system = None
                status_lbl.value = f"✅ Применена: {chosen}"
                self.page.update()
        
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Настройки", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Выберите LLM модель:", size=14, weight=ft.FontWeight.BOLD),
                    model_dropdown,
                    status_lbl,
                    ft.Divider(),
                    ft.Text(f"База: PRL-27СМ Documentation\nВерсия: {APP_VERSION}", size=13, color=self.theme["text_secondary"]),
                ], tight=True, spacing=10),
                width=400,
                padding=20
            ),
            actions=[
                ft.FilledButton("Закрыть", on_click=lambda e: self.page.close(dlg)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dlg)


def main(page: ft.Page):
    AviationRAGApp(page)

if __name__ == "__main__":
    ft.app(target=main)