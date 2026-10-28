import flet as ft
import json
import threading
from pathlib import Path
import sys
import platform
import re

sys.path.append(str(Path(__file__).parent))
from smart_rag import SmartRAG

try:
    from document_processor import add_document, list_documents
except ImportError:
    add_document = None
    list_documents = None

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
ASSETS_DIR = Path(__file__).parent / "assets"

AVAILABLE_MODELS = {
    "Qwen 2.5 (14B)": "qwen2.5:14b",
    "Qwen 2.5 Coder Abliterated (14B)": "huihui_ai/qwen2.5-coder-abliterate:14b",
    "Qwen 3 Abliterated (14B)": "huihui_ai/qwen3-abliterated:14b",
    "Qwen 3.5 Uncensored Aggressive (9B)": "fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b",
    "Qwen 2.5 (7B)": "qwen2.5:7b",
    "Gemma 2 (9B)": "gemma2:9b",
}
DEFAULT_MODEL_DISPLAY = "Qwen 2.5 (14B)"

def load_assets():
    assets = {}
    print(f"[ASSETS] Path: {ASSETS_DIR}", flush=True)
    
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        assets["logo"] = str(logo_path)
    
    for name in ["assistant", "user"]:
        path = ASSETS_DIR / "avatars" / f"{name}.png"
        if path.exists():
            assets[name] = str(path)
    
    for name in ["clear", "new_chat", "send", "settings"]:
        path = ASSETS_DIR / "icons" / f"{name}.png"
        if path.exists():
            assets[name] = str(path)
    
    # Умный поиск иконки для добавления файла
    add_found = False
    for add_name in ["add.png", "plus.png", "attach.png", "add_file.png"]:
        add_path = ASSETS_DIR / "icons" / add_name
        if add_path.exists():
            assets["add"] = str(add_path)
            add_found = True
            print(f"[ASSETS] ✓ Найдена иконка добавления: {add_name}", flush=True)
            break
    
    if not add_found:
        print("[WARN] Иконка добавления файла не найдена! Проверь названия файлов в папке assets/icons/", flush=True)
        # В крайнем случае используем new_chat как заглушку, но лучше переименовать файл
        if "new_chat" in assets:
            assets["add"] = assets["new_chat"]
    
    bg_path = ASSETS_DIR / "background.png"
    if bg_path.exists():
        assets["background"] = str(bg_path)
    
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        assets["icon"] = str(icon_path)
    
    return assets

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
        self.attachments_row = None  # Для хранения строки с чипами файлов
        
        self._streaming_chat_id = None
        self._streaming_row = None
        self._last_prl_path = self._load_prl_path()
        self._last_kb_path = "./knowledge_base"
        
        self._setup_page()
        self._build_ui()
        self.page.update()
        self._load_current_chat()
        
        # ПРОВЕРКА ПЕРВОГО ЗАПУСКА (вызываем напрямую, без потока!)
        prl_path = self._load_prl_path()
        if not prl_path:
            print("[DEBUG] Первый запуск — показываем диалог выбора папки PRL-27", flush=True)
            self._show_first_launch_dialog() 

        # ФОНОВАЯ ПРЕДЗАГРУЗКА тяжёлых модулей, чтобы перестроение индекса
        # не зависало молча на импортах torch/pdfplumber/langchain
        def _warmup_imports():
            try:
                print("[WARMUP] Предзагрузка тяжёлых модулей в фоне...", flush=True)
                import data_ingestion  # noqa
                import vector_store    # noqa
                print("[WARMUP] Тяжёлые модули готовы к работе", flush=True)
            except Exception as ex:
                print(f"[WARMUP] Ошибка предзагрузки: {ex}", flush=True)
        
        threading.Thread(target=_warmup_imports, daemon=True).start()
    
    
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
        self.page.spacing = 0
        
        if "icon" in self.assets:
            self.page.window.icon = self.assets["icon"]

    def _make_icon_button(self, icon_path, on_click, tooltip="", size=32, bgcolor=None):
        """Создает кнопку с кастомной PNG-иконкой"""
        img = ft.Image(
            src=icon_path,
            width=size,
            height=size,
            fit=ft.ImageFit.CONTAIN, # Сохраняет пропорции
            tooltip=tooltip,
        )
        return ft.Container(
            content=img,
            on_click=on_click,
            ink=True,  # Эффект нажатия (волна)
            border_radius=8,  # Слегка скругленные углы выглядят лучше для кастомных иконок
            padding=4,  # Уменьшили отступ, чтобы иконка была крупнее
            bgcolor=bgcolor,
        )

    def _build_ui(self):
        self.chat_list_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=4)
        
        btn_accent_style = ft.ButtonStyle(
            bgcolor=self.theme["accent"], color="#ffffff", shape=ft.RoundedRectangleBorder(radius=10)
        )
        btn_text_style = ft.ButtonStyle(color=self.theme["text_primary"])
        
        logo_control = None
        if "logo" in self.assets:
            logo_control = ft.Image(src=self.assets["logo"], height=60, width=60)
        
        self.sidebar = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        # Логотип (icon.png) - увеличен и отцентрирован
                        ft.Container(
                            content=ft.Image(
                                src=self.assets["icon"] if "icon" in self.assets else self.assets.get("logo"),
                                height=140,  # Ещё больше
                                width=140,
                                fit=ft.ImageFit.CONTAIN,
                            ),
                            alignment=ft.alignment.center,  # Центрируем контейнер
                            width=float("inf"),  # Занимает всю ширину
                        ),
                        ft.Text("Aviation RAG", size=22, weight=ft.FontWeight.BOLD, color=self.theme["text_primary"], text_align=ft.TextAlign.CENTER),
                        ft.Text("AI Engine v1.0", size=12, color=self.theme["text_secondary"], text_align=ft.TextAlign.CENTER),
                    ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.padding.symmetric(horizontal=16, vertical=20),
                    width=float("inf"),  # Контейнер на всю ширину сайдбара
                ),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.ElevatedButton(
                    "＋ Новый чат",
                    on_click=self._handle_new_chat,
                    style=btn_accent_style,
                    width=float("inf"),
                ),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.Container(content=self.chat_list_column, expand=True),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(
                                src=self.assets["settings"],
                                width=20,
                                height=20,
                                fit=ft.ImageFit.CONTAIN,
                            ) if "settings" in self.assets else ft.Icon(ft.Icons.SETTINGS, size=20, color=self.theme["text_primary"]),
                            ft.Text("Настройки", size=13, color=self.theme["text_primary"]),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    on_click=self._show_settings,
                    ink=True,  # Эффект нажатия
                    padding=ft.padding.symmetric(horizontal=12, vertical=10),
                    border_radius=8,
                    width=float("inf"),
                ),
            ], spacing=0),
            width=280,
            bgcolor=self.theme["bg_sidebar"],
        )
        
        self.status_text = ft.Text("● Готов", size=13, weight=ft.FontWeight.BOLD, color=self.theme["status_ready"])
        self.model_label = ft.Text(f"{self.current_model_display}  •  PRL-27СМ RAG", size=14, weight=ft.FontWeight.BOLD, color=self.theme["text_secondary"])
        
        self.header = ft.Container(
            content=ft.Row([self.model_label, ft.Container(expand=True), self.status_text]),
            padding=ft.padding.symmetric(horizontal=20, vertical=12),
        )
        
        self.messages_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12)
        
        self.welcome = ft.Container(
            content=ft.Column([
                # Логотип вместо самолётика
                ft.Image(
                    src=self.assets["logo"],
                    height=120,
                    width=120,
                    fit=ft.ImageFit.CONTAIN,
                ) if "logo" in self.assets else ft.Text("✈️", size=80),
                ft.Text("Чем могу помочь?", size=36, weight=ft.FontWeight.BOLD, color=self.theme["text_primary"]),
                ft.Text("Задайте вопрос по документации ПРЛ-27СМ", size=16, color=self.theme["text_secondary"]),
                ft.Container(height=40),
                ft.Row([
                    ft.ElevatedButton("Как включить излучение шкафа 276ГГ02?", on_click=lambda e: self._send_example(e.control.text), width=320, height=60),
                    ft.ElevatedButton("Что такое сигнал PPS?", on_click=lambda e: self._send_example(e.control.text), width=320, height=60),
                ], wrap=True, spacing=12, alignment=ft.MainAxisAlignment.CENTER),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12),
            expand=True,
            alignment=ft.alignment.center,
        )
        
        self.chat_stack = ft.Stack([self.welcome, self.messages_column], expand=True)
        
        self.chat_area = ft.Container(
            content=ft.Column([self.header, self.chat_stack], spacing=0),
            expand=True,
        )
        
        self.input_field = ft.TextField(
            hint_text="Message RAG Assistant...",
            multiline=True,
            min_lines=1,
            max_lines=20,  # Увеличили с 5 до 20
            expand=True,   # ДОБАВЛЕНО: поле будет занимать доступное пространство
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            border_color=self.theme["border"],
            focused_border_color=self.theme["accent"],
            text_style=ft.TextStyle(size=15, font_family="main"),
            on_submit=self._handle_send,
            # ДОБАВЛЕНО: автоматическая подстройка высоты
            adaptive=True,
        )
        
        self.folder_picker = ft.FilePicker(on_result=self._on_folder_pick_result)
        self.page.overlay.append(self.folder_picker)
        self._folder_pick_target = None
        self.page.update()  # Обязательно обновляем страницу
        
        # ИСПРАВЛЕНО: Структура поля ввода теперь Column, чтобы чипы файлов были НАД строкой ввода
        self.attachments_row = ft.Row([], wrap=True, spacing=4, visible=False)
        
        self.input_area = ft.Container(
            content=ft.Column([
                self.attachments_row,
                ft.Row([
                    self._make_icon_button(
                        self.assets.get("add", self.assets.get("new_chat")), # Безопасный фоллбэк
                        on_click=self._handle_attach_click,
                        tooltip="Прикрепить документ",
                        size=36, # Сделали крупнее
                    ),
                    self.input_field,
                    self._make_icon_button(
                        self.assets["send"],
                        on_click=self._handle_send,
                        tooltip="Отправить",
                        size=32, # Сделали крупнее
                        bgcolor=self.theme["accent"],
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.END)
            ], spacing=8),
            padding=ft.padding.all(20),
            bgcolor=self.theme["bg_main"],
        )

        self.page.add(
            ft.Row([
                self.sidebar,
                ft.VerticalDivider(width=1, color=self.theme["border"]),
                ft.Column([self.chat_area, ft.Divider(height=1, color=self.theme["border"]), self.input_area], spacing=0, expand=True),
            ], expand=True, spacing=0)
        )

    def _render_content_with_code_blocks(self, content: str):
        import re
        widgets = []
        
        # Более надежное регулярное выражение: допускает пробелы после ``` и перед закрывающими ```
        pattern = r'```([a-zA-Z0-9_]*)\s*\n(.*?)\s*```'
        
        # re.split с группами захвата вернет: [текст, язык, код, текст, язык, код, ...]
        parts = re.split(pattern, content, flags=re.DOTALL)
        
        i = 0
        while i < len(parts):
            if i % 3 == 0:
                # Обычный текст
                text = parts[i].strip()
                if text:
                    md = ft.Markdown(
                        value=text,
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                    )
                    widgets.append(ft.Container(content=md, expand=True))
                    
            elif i % 3 == 1:
                # Язык программирования (parts[i])
                lang = parts[i].strip()
                # Сам код (parts[i+1])
                code = parts[i+1] if i+1 < len(parts) else ""
                
                code_text = ft.Text(
                    code,
                    size=13,
                    color="#e6edf3",
                    font_family="Courier New",
                    selectable=True,
                )
                
                copy_btn = ft.IconButton(
                    icon=ft.Icons.COPY,
                    icon_size=16,
                    tooltip="Копировать код",
                    style=ft.ButtonStyle(color="#8b949e"),
                    on_click=lambda e, c=code: self._copy_code_to_clipboard(c),
                )
                
                code_block = ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Text(lang.upper() if lang else "CODE", size=11, color="#8b949e", weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            copy_btn,
                        ]),
                        ft.Container(
                            content=code_text,
                            padding=ft.padding.all(12),
                        ),
                    ], spacing=4),
                    bgcolor="#0d1117",
                    border_radius=8,
                    padding=ft.padding.all(8),
                    margin=ft.margin.symmetric(vertical=8),
                )
                widgets.append(code_block)
                i += 1  # Пропускаем индекс с кодом, так как мы его уже обработали
            
            i += 1
        
        # Fallback: если по какой-то причине список пуст, но контент есть, рендерим как обычный markdown
        if not widgets and content.strip():
            md = ft.Markdown(value=content, selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)
            widgets.append(ft.Container(content=md, expand=True))
            
        return widgets

    def _copy_code_to_clipboard(self, code: str):
        """Копирует код в буфер обмена"""
        try:
            self.page.set_clipboard(code)
            self._show_toast("Код скопирован!", color="#10b981", duration=1500)
        except Exception as e:
            print(f"[ERROR] Ошибка копирования: {e}", flush=True)

    def _handle_attach_click(self, e):
        print("[DEBUG] Клик на кнопку +", flush=True)
        self.file_picker.pick_files(
            dialog_title="Выберите документ для загрузки",
            allowed_extensions=["pdf", "docx", "txt", "md", "csv", "xlsx"],
            allow_multiple=False,
        )
        
        if platform.system() == "Darwin":
            # Правильный AppleScript для получения POSIX пути
            script = '''
            try
                set theFile to choose file with prompt "Выберите документ для загрузки"
                return POSIX path of theFile
            on error
                return "CANCELLED"
            end try
            '''
            
            try:
                result = subprocess.run(
                    ['osascript', '-e', script], 
                    capture_output=True, 
                    text=True, 
                    timeout=300
                )
                
                if result.returncode == 0:
                    file_path = result.stdout.strip()
                    if file_path and file_path != "CANCELLED" and not file_path.startswith("alias"):
                        print(f"[DEBUG] Выбран файл: {file_path}", flush=True)
                        
                        self.status_text.value = "● Обрабатываю документ..."
                        self.status_text.color = self.theme["status_busy"]
                        self.page.update()
                        threading.Thread(target=self._process_document, args=(file_path,), daemon=True).start()
                    else:
                        print(f"[DEBUG] Выбор отменен или неверный путь: {file_path}", flush=True)
                else:
                    print(f"[ERROR] osascript вернул код {result.returncode}: {result.stderr}", flush=True)
                    
            except subprocess.TimeoutExpired:
                print("[ERROR] Таймаут ожидания выбора файла", flush=True)
            except Exception as ex:
                print(f"[ERROR] Ошибка: {ex}", flush=True)
        else:
            self.file_picker.pick_files(
                dialog_title="Выберите документ для загрузки",
                allowed_extensions=["pdf", "docx", "txt", "md", "csv", "xlsx"],
                allow_multiple=False,
            )

    def _process(self, user_input: str):
        try:
            if self.rag_system is None:
                self.rag_system = SmartRAG(model_name=self.current_model_ollama)
            
            original_chat_id = self.chat_manager.current_chat_id
            self._streaming_chat_id = original_chat_id
            
            self._stream_cancel_flag = {"cancelled": False}
            self._streaming_text = ""
            
            self.page.run_thread(self._add_streaming_placeholder)
            
            chat = self.chat_manager.get_current_chat()
            chat_history = chat["messages"][-5:] if chat and chat["messages"] else []
            
            def on_token(full_text):
                if self._stream_cancel_flag.get("cancelled"):
                    return 
                self._streaming_text = full_text
                self.page.run_thread(self._update_streaming_message, full_text)
            
            # 🆕 Получаем кортеж (ответ, источники)
            response_data = self.rag_system.query_stream(
                user_input,
                chat_history=chat_history,
                chat_id=original_chat_id,
                on_token=on_token,
                cancel_flag=self._stream_cancel_flag
            )
            
            if isinstance(response_data, tuple):
                response, real_sources = response_data
            else:
                response, real_sources = response_data, []
            
            if self._stream_cancel_flag.get("cancelled") or original_chat_id not in self.chat_manager.chats:
                print(f"[STREAM] Генерация была отменена, очищаем UI", flush=True)
                self.page.run_thread(self._cleanup_cancelled_stream)
                return
            
            clean = re.sub(r'\n?\[Источник:[^\]]+\]', '', response).strip()
            clean = clean.replace("[С поиском]:\n", "").replace("[Без поиска]: ", "")
            
            self.page.run_thread(self._finalize_streaming_message, clean, real_sources, original_chat_id)
            
        except Exception as e:
            import traceback
            print(f"[ERROR] {e}\n{traceback.format_exc()}")
            self.page.run_thread(self._finalize_streaming_message, f"Ошибка: {e}", [], getattr(self, '_streaming_chat_id', None))

    def _cleanup_cancelled_stream(self):
        """Очищает интерфейс, если стриминг был прерван удалением чата"""
        if hasattr(self, '_streaming_row') and self._streaming_row and self._streaming_row in self.messages_column.controls:
            self.messages_column.controls.remove(self._streaming_row)
        
        self.is_processing = False
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self.page.update()

    def _on_file_pick_result(self, e: ft.FilePickerResultEvent):
        if e.files:
            file_path = e.files[0].path
            self.status_text.value = "● Обрабатываю документ..."
            self.status_text.color = self.theme["status_busy"]
            self.page.update()
            threading.Thread(target=self._process_document, args=(file_path,), daemon=True).start()

    def _on_folder_pick_result(self, e: ft.FilePickerResultEvent):
        """Обработчик выбора папки через нативный диалог Flet"""
        target = self._folder_pick_target
        self._folder_pick_target = None
        path = e.path
        
        if not path:
            print("[DEBUG] Выбор папки отменен", flush=True)
            return
        
        clean = path.rstrip('/')
        print(f"[DEBUG] Выбрана папка (target={target}): {clean}", flush=True)
        
        if target == 'prl' and hasattr(self, 'prl_folder_path'):
            self.prl_folder_path.value = clean
            self.prl_folder_path.update()
        elif target == 'kb' and hasattr(self, 'kb_folder_path'):
            self.kb_folder_path.value = clean
            self.kb_folder_path.update()
        elif target == 'first' and hasattr(self, 'prl_first_path'):
            self.prl_first_path.value = clean
            self.prl_first_path.update()
        
        self.page.update()

    def _apply_folder_path(self, target: str, path: str):
        """Применяет выбранный путь к нужному полю"""
        clean = path.rstrip('/')
        print(f"[DEBUG] Применяю путь ({target}): {clean}", flush=True)
        if target == 'prl':
            self._last_prl_path = clean
            if hasattr(self, 'prl_folder_path'):
                self.prl_folder_path.value = clean
                self.prl_folder_path.update()
        elif target == 'kb':
            self._last_kb_path = clean
            if hasattr(self, 'kb_folder_path'):
                self.kb_folder_path.value = clean
                self.kb_folder_path.update()
        elif target == 'first':
            self._last_prl_path = clean
            if hasattr(self, 'prl_first_path'):
                self.prl_first_path.value = clean
                self.prl_first_path.update()
        self.page.update()

    def _reopen_parent_dialog(self, target: str):
        """Создаёт родительское окно ЗАНОВО (свежий экземпляр диалога)"""
        import time
        time.sleep(0.3)  # даём Flutter дочиста закрыть окно браузера папок
        try:
            if target == 'first':
                self.page.run_thread(self._show_first_launch_dialog)
            else:
                self.page.run_thread(self._show_settings, None)
        except Exception as ex:
            print(f"[DEBUG] Не удалось снова открыть окно: {ex}", flush=True)

    def _open_folder_browser(self, target: str):
        """Встроенный браузер папок (100% работает, без системных диалогов)"""
        # Стартовая папка: текущее значение поля или домашняя папка
        start = str(Path.home())
        if target == 'prl' and hasattr(self, 'prl_folder_path') and self.prl_folder_path.value:
            start = self.prl_folder_path.value
        elif target == 'kb' and hasattr(self, 'kb_folder_path') and self.kb_folder_path.value:
            start = self.kb_folder_path.value
        
        path_field = ft.TextField(
            value=start,
            expand=True,
            text_size=13,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            border_color=self.theme["border"],
        )
        list_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=2)
        
        def refresh(*_):
            p = Path(path_field.value).expanduser()
            if not p.is_dir():
                return
            path_field.value = str(p)
            list_column.controls.clear()
            try:
                dirs = sorted([d for d in p.iterdir() if d.is_dir() and not d.name.startswith('.')])
            except Exception:
                dirs = []
            for d in dirs:
                list_column.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.FOLDER, size=18, color=self.theme["accent"]),
                            ft.Text(d.name, size=13, color=self.theme["text_primary"]),
                        ], spacing=8),
                        padding=ft.padding.symmetric(horizontal=8, vertical=6),
                        border_radius=6,
                        ink=True,
                        on_click=lambda e, dd=d: (setattr(path_field, 'value', str(dd)), refresh()),
                    )
                )
            if not dirs:
                list_column.controls.append(
                    ft.Text("(нет вложенных папок)", size=12, color=self.theme["text_secondary"])
                )
            self.page.update()
        
        path_field.on_submit = lambda e: refresh()
        
        def go_up(e):
            p = Path(path_field.value).expanduser().parent
            path_field.value = str(p)
            refresh()
        
        def confirm(e):
            self.page.close(browser_dlg)
            self._apply_folder_path(target, path_field.value)
            # Возвращаем пользователя в родительское окно (настройки / первый запуск)
            self._reopen_parent_dialog(target)
        
        def cancel(e):
            self.page.close(browser_dlg)
            self._reopen_parent_dialog(target)
        
        browser_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Выбор папки", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.IconButton(ft.Icons.ARROW_UPWARD, tooltip="Вверх", on_click=go_up),
                        path_field,
                    ], spacing=6),
                    ft.Text("Двойной клик по папке — войти. Или вставь путь в поле и нажми Enter.",
                            size=11, color=self.theme["text_secondary"]),
                    ft.Divider(height=1),
                    ft.Container(content=list_column, height=320),
                ], spacing=8),
                width=520,
            ),
            actions=[
                ft.FilledButton("Выбрать эту папку", on_click=confirm,
                                style=ft.ButtonStyle(bgcolor=self.theme["accent"], color="#ffffff")),
                ft.TextButton("Отмена", on_click=cancel),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        refresh()
        self.page.open(browser_dlg)

    def _update_chat_list(self):
        self.chat_list_column.controls.clear()
        self.chat_list_controls.clear()
        
        for chat_id, chat_data in reversed(list(self.chat_manager.chats.items())):
            is_current = chat_id == self.chat_manager.current_chat_id
            name = chat_data["name"][:28] + ("..." if len(chat_data["name"]) > 28 else "")
            
            # Создаем строку с названием чата и кнопкой удаления
            chat_row = ft.Row(
                [
                    ft.Container(
                        content=ft.Text(name, size=13, color="#ffffff" if is_current else self.theme["text_primary"]),
                        expand=True,
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    ),
                    self._make_icon_button(
                        self.assets["clear"],
                        on_click=lambda e, cid=chat_id: self._delete_chat(cid),
                        tooltip="Удалить чат",
                        size=24, # Сделали крупнее
                    ),
                ],
                spacing=0,
            )
            
            # Обертка для клика по всей строке
            chat_container = ft.Container(
                content=chat_row,
                bgcolor=self.theme["accent"] if is_current else None,
                border_radius=8,
                on_click=lambda e, cid=chat_id: (
                    self._show_toast("Дождитесь завершения ответа!", color="#f59e0b") 
                    if self.is_processing 
                    else self._switch_chat(cid)
                ),
                padding=ft.padding.symmetric(horizontal=4, vertical=2),
            )
            
            self.chat_list_column.controls.append(chat_container)
            self.chat_list_controls[chat_id] = chat_container
        
        self.page.update()

    def _delete_chat(self, chat_id):
        
        #  ОСТАНОВКА ГЕНЕРАЦИИ ПРИ УДАЛЕНИИ ЧАТА
        if chat_id == getattr(self, '_streaming_chat_id', None):
            print(f"[DELETE] Останавливаем генерацию при удалении чата", flush=True)
            if hasattr(self, '_stream_cancel_flag'):
                self._stream_cancel_flag["cancelled"] = True
            
            if hasattr(self, '_streaming_row') and self._streaming_row in self.messages_column.controls:
                self.messages_column.controls.remove(self._streaming_row)
            
            self.is_processing = False
            self.status_text.value = "● Готов"
            self.status_text.color = self.theme["status_ready"]
            self.page.update()
        
        chat_name = self.chat_manager.chats.get(chat_id, {}).get("name", "этот чат")
        
        def confirm_delete(e):
            self.page.close(dlg)
            
            # УСТАНАВЛИВАЕМ ФЛАГ ОТМЕНЫ, если удаляем чат, в котором идёт генерация
            if chat_id == getattr(self, '_streaming_chat_id', None):
                print(f"[STREAM] Устанавливаем флаг отмены для чата {chat_id}", flush=True)
                if hasattr(self, '_stream_cancel_flag'):
                    self._stream_cancel_flag["cancelled"] = True
            
            # Логика переключения на другой чат
            if chat_id == self.chat_manager.current_chat_id:
                other_chats = [cid for cid in self.chat_manager.chats.keys() if cid != chat_id]
                if other_chats:
                    self.chat_manager.current_chat_id = other_chats[-1]
                else:
                    self.chat_manager.create_new_chat()
            
            self.chat_manager.delete_chat(chat_id)
            self._update_chat_list()
            self._load_current_chat()
            
            self._show_toast(f"Чат '{chat_name}' удален", color="#334155", duration=2000)
        
        def cancel_delete(e):
            self.page.close(dlg)
        
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Удалить чат?", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Text(f"Вы уверены, что хотите удалить чат '{chat_name}'?\nЭто действие нельзя отменить.", size=14),
            actions=[
                ft.TextButton("Отмена", on_click=cancel_delete),
                ft.FilledButton("Удалить", on_click=confirm_delete, style=ft.ButtonStyle(bgcolor="#ef4444", color="#ffffff")),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        self.page.open(dlg)

    def _handle_new_chat(self, e):
        self.chat_manager.create_new_chat()
        self._update_chat_list()
        self._load_current_chat()

    def _switch_chat(self, chat_id):
        #  ОСТАНОВКА ГЕНЕРАЦИИ ПРИ ПЕРЕКЛЮЧЕНИИ ЧАТА
        if self.is_processing:
            print(f"[SWITCH] Останавливаем генерацию при переключении чата", flush=True)
            if hasattr(self, '_stream_cancel_flag'):
                self._stream_cancel_flag["cancelled"] = True
            
            # Очищаем streaming placeholder из текущего чата
            if hasattr(self, '_streaming_row') and self._streaming_row in self.messages_column.controls:
                self.messages_column.controls.remove(self._streaming_row)
                print(f"[SWITCH] Удален streaming placeholder", flush=True)
            
            self.is_processing = False
            self.status_text.value = "● Готов"
            self.status_text.color = self.theme["status_ready"]
            self.page.update()
        
        # Теперь переключаемся
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
                            padding=6,
                        )
                    )
            
            bubble = ft.Container(
                content=ft.Column(
                    attach_controls + [
                        ft.Text(
                            content, 
                            size=15, 
                            color="#ffffff", 
                            selectable=True,
                            width=None,  # Убираем фиксированную ширину
                        )
                    ], 
                    spacing=8
                ),
                bgcolor=self.theme["bg_bubble_user"],
                padding=16,
                border_radius=20,
                expand=True,  # ДОБАВЛЕНО: контейнер занимает доступное пространство
            )
            avatar = ft.Image(src=self.assets["user"], width=40, height=40) if "user" in self.assets else ft.Text("👤", size=28)
            
            row = ft.Row(
                [
                    ft.Container(expand=True),  # Пустой контейнер для прижатия вправо
                    bubble,
                    avatar,
                ], 
                vertical_alignment=ft.CrossAxisAlignment.START,
                expand=True,  # ДОБАВЛЕНО: строка занимает всю ширину
            )
            
        else:
            # Рендерим контент с кнопками копирования кода
            content_widgets = self._render_content_with_code_blocks(content)
            
            # Добавляем источники ПРАВИЛЬНО (не как markdown-список)
            if sources:
                source_text = "📎 Источники: " + ", ".join(sources[:3])
                if len(sources) > 3:
                    source_text += f" и ещё {len(sources) - 3}"
                
                source_widget = ft.Container(
                    content=ft.Text(
                        source_text, 
                        size=11, 
                        color=self.theme["text_secondary"],
                    ),
                    bgcolor="rgba(255,255,255,0.05)",
                    border_radius=6,
                    padding=ft.padding.all(8), # Оставили только один padding
                )
                content_widgets.append(source_widget)
            
            bubble = ft.Container(
                content=ft.Column(content_widgets, spacing=2),
                bgcolor=self.theme["bg_bubble_ai"],
                padding=16,
                border_radius=16,
                expand=True,
            )
            avatar = ft.Image(src=self.assets["assistant"], width=40, height=40) if "assistant" in self.assets else ft.Text("🤖", size=28)
            
            row = ft.Row(
                [avatar, bubble],
                vertical_alignment=ft.CrossAxisAlignment.START,
                expand=True,
            )
        
        self.messages_column.controls.append(row)
        self.welcome.visible = False
        self.page.update()
        self.messages_column.scroll_to(offset=-1, duration=300)

    def _handle_send(self, e):
        text = self.input_field.value.strip()
        if not text or self.is_processing:
            if self.is_processing:
                self._show_toast(" Подождите завершения текущего ответа!", color="#f59e0b")
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
            # ИСПРАВЛЕНО: правильный способ показать snack bar в Flet 0.28.3
            snack_bar = ft.SnackBar(
                content=ft.Text(f"Ошибка: {info['error']}"),
                bgcolor="#ef4444",
            )
            self.page.overlay.append(snack_bar)
            snack_bar.open = True
            self.page.update()
        else:
            self._show_toast(f"Загружено: {info['filename']} ({info['chunks']} фр.)", color="#10b981", duration=2500)
            
            chat = self.chat_manager.get_current_chat()
            if chat:
                if "attachments" not in chat or chat["attachments"] is None:
                    chat["attachments"] = []
                if info["filename"] not in chat["attachments"]:
                    chat["attachments"].append(info["filename"])
                self.chat_manager.save()
        
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self._update_attachments_display()
        self.page.update()

    def _update_attachments_display(self):
        chat = self.chat_manager.get_current_chat()
        attachments = chat.get("attachments", []) if chat else []
        
        self.attachments_row.controls.clear()
        
        if attachments:
            for name in attachments:
                chip = ft.Chip(
                    label=ft.Text(name, size=11, color="#dbeafe"),
                    bgcolor="#1e3a8a",
                    padding=4,
                    # Используем стандартную иконку закрытия, так как ft.Icon не поддерживает пути к PNG
                    delete_icon=ft.Icon(ft.Icons.CLOSE, size=14, color="#94a3b8"),
                    on_delete=lambda e, n=name: self._remove_attachment(n),
                )
                self.attachments_row.controls.append(chip)
            self.attachments_row.visible = True
        else:
            self.attachments_row.visible = False
            
        self.page.update()

    def _remove_attachment(self, filename):
        """Удаляет документ из текущего чата"""
        chat = self.chat_manager.get_current_chat()
        if chat and "attachments" in chat:
            if filename in chat["attachments"]:
                chat["attachments"].remove(filename)
                self.chat_manager.save()
                
                # Также удаляем из БД если есть функция
                try:
                    from document_processor import list_documents, remove_document
                    docs = list_documents(chat_id=self.chat_manager.current_chat_id or "global", pending_only=True)
                    for doc in docs:
                        if doc["filename"] == filename:
                            remove_document(doc["doc_id"])
                            break
                except Exception as e:
                    print(f"[DEBUG] Ошибка удаления из БД: {e}", flush=True)
                
                self._update_attachments_display()
                
                # Показываем уведомление
                self._show_toast(f"Удалено: {filename}", color="#334155", duration=2000)
    
    def _add_streaming_placeholder(self):
        """Добавляет пустое сообщение ассистента в UI"""
        md = ft.Markdown(
            value="...",
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        )
        
        self._streaming_bubble = ft.Container(
            content=ft.Column([ft.Container(content=md, expand=True)], spacing=2),
            bgcolor=self.theme["bg_bubble_ai"],
            padding=16,
            border_radius=16,
            expand=True,
        )
        
        avatar = ft.Image(src=self.assets["assistant"], width=40, height=40) if "assistant" in self.assets else ft.Text("🤖", size=28)
        
        self._streaming_row = ft.Row(
            [avatar, self._streaming_bubble],
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        )
        
        self.messages_column.controls.append(self._streaming_row)
        self.welcome.visible = False
        self.page.update()
        self.messages_column.scroll_to(offset=-1, duration=100)
    
    def _update_streaming_message(self, text):
        """Обновляет текст streaming-сообщения с кнопками копирования кода"""
        if hasattr(self, '_streaming_bubble') and self._streaming_bubble:
            content_widgets = self._render_content_with_code_blocks(text)
            self._streaming_bubble.content = ft.Column(content_widgets, spacing=2)
            self.page.update()
            self.messages_column.scroll_to(offset=-1, duration=50)
    
    def _finalize_streaming_message(self, response, sources, target_chat_id=None):
        """Заменяет streaming-сообщение на финальное с источниками"""
        # Проверяем, что целевой чат всё ещё существует
        if target_chat_id and target_chat_id not in self.chat_manager.chats:
            print(f"[FINALIZE] Чат {target_chat_id} удалён, не добавляем сообщение", flush=True)
            return
        
        # Проверяем, что это всё ещё активный чат
        if target_chat_id and self.chat_manager.current_chat_id != target_chat_id:
            print(f"[FINALIZE] Чат изменён, не добавляем сообщение", flush=True)
            return
        
        # Удаляем placeholder, если он есть
        if hasattr(self, '_streaming_row') and self._streaming_row and self._streaming_row in self.messages_column.controls:
            self.messages_column.controls.remove(self._streaming_row)
        
        # Добавляем финальное сообщение
        self._add_message_to_ui("assistant", response, sources=sources)
        self.chat_manager.add_message("assistant", response, sources=sources)
        
        self.is_processing = False
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self.page.update()

    def _show_toast(self, message: str, color: str = "#334155", duration: int = 2500):
        """Показывает компактное toast-уведомление в правом верхнем углу"""
        toast = ft.Container(
            content=ft.Text(message, size=12, color="#ffffff"),
            bgcolor=color,
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            border_radius=8,
            right=20,
            top=70,  # Под статусом модели
        )
        
        # Добавляем toast в overlay страницы
        self.page.overlay.append(toast)
        self.page.update()
        
        # Автоматически удаляем через duration мс
        def remove_toast():
            import time
            time.sleep(duration / 1000)
            if toast in self.page.overlay:
                self.page.overlay.remove(toast)
                self.page.update()
        
        threading.Thread(target=remove_toast, daemon=True).start()

    def _on_response_ready(self, response, sources):
        self._add_message_to_ui("assistant", response, sources=sources)
        self.chat_manager.add_message("assistant", response, sources=sources)
        self.is_processing = False
        self.status_text.value = "● Готов"
        self.status_text.color = self.theme["status_ready"]
        self.page.update()

    def _save_prl_path(self, path: str):
        """Сохраняет путь к PRL-27 базе в config.json"""
        config_path = Path(__file__).parent / "config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            else:
                config = {}
            
            config["knowledge_base_path"] = path
            
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            print(f"[DEBUG] Путь PRL сохранён в config.json: {path}", flush=True)
        except Exception as e:
            print(f"[ERROR] Ошибка сохранения пути: {e}", flush=True)

    def _load_prl_path(self) -> str:
        """Загружает путь к PRL-27 базе из config.json"""
        config_path = Path(__file__).parent / "config.json"
        try:
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                return config.get("knowledge_base_path", "")
        except Exception as e:
            print(f"[ERROR] Ошибка загрузки пути: {e}", flush=True)
        return ""

    def _show_first_launch_dialog(self):
        """Показывает приветственный диалог при первом запуске"""
        
        # Создаем диалог СНАЧАЛА, чтобы он был доступен функциям ниже
        self.first_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Добро пожаловать в Aviation RAG!", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Для начала работы укажите папку с технической документацией ПРЛ-27СМ:", size=14),
                    ft.Container(height=10),
                ], tight=True, spacing=10),
                width=450,
                padding=20
            )
        )
        
        def choose_folder(e):
            self._open_folder_browser('first')

        def start_app(e):
            folder = self.prl_first_path.value.strip()
            if not folder:
                self._show_toast("Укажите путь к папке!", color="#ef4444")
                return
            
            if not Path(folder).exists():
                self._show_toast("Папка не существует!", color="#ef4444")
                return
            
            self._save_prl_path(folder)
            self.page.close(self.first_dlg)
            self._show_toast("База знаний настроена! Начинаем индексацию...", color="#10b981", duration=3000)
            
            # Сразу запускаем перестроение индекса после выбора
            self._rebuild_prl_index_direct(folder)

        self.prl_first_path = ft.TextField(
            label="Путь к папке с документами PRL-27",
            value=self._last_prl_path or "",   # <-- добавить value
            width=300,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            hint_text="Нажмите иконку папки справа, чтобы выбрать",
        )

        choose_first_btn = ft.IconButton(
            icon=ft.Icons.FOLDER,
            tooltip="Выбрать папку",
            on_click=choose_folder,
            style=ft.ButtonStyle(color=self.theme["text_primary"]),
        )

        # Обновляем содержимое диалога
        self.first_dlg.content = ft.Container(
            content=ft.Column([
                ft.Text("Для начала работы укажите папку с технической документацией ПРЛ-27СМ:", size=14),
                ft.Container(height=10),
                ft.Row([self.prl_first_path, choose_first_btn], spacing=10),
                ft.Container(height=10),
                ft.Text("Нажмите на иконку папки и выберите папку с документами.", size=12, color=self.theme["text_secondary"], italic=True),
            ], tight=True, spacing=10),
            width=450,
            padding=20
        )
        
        self.first_dlg.actions = [
            ft.FilledButton("Начать работу", on_click=start_app, style=ft.ButtonStyle(bgcolor=self.theme["accent"], color="#ffffff")),
        ]
        self.first_dlg.actions_alignment = ft.MainAxisAlignment.END
        
        self.page.open(self.first_dlg)

    def _close_dialog_and_toast(self, dlg, message, color, duration):
        try:
            self.page.close(dlg)
        except Exception:
            pass
        self._show_toast(message, color=color, duration=duration)
        self.page.update()

    def _close_dialog_and_toast(self, dlg, message, color, duration):
        """Закрывает диалог и показывает toast (безопасно из любого потока)"""
        try:
            self.page.close(dlg)
        except Exception:
            pass
        self._show_toast(message, color=color, duration=duration)
        self.page.update()

    def _clear_all_data(self, e):
        """Полная очистка всех данных приложения (Factory Reset)"""
        import shutil
        
        def confirm_clear(e):
            self.page.close(clear_dlg)
            self._show_toast("Очистка данных...", color="#f59e0b", duration=99999)
            
            def run_clear():
                try:
                    base_dir = Path(__file__).parent
                    folders_to_delete = [
                        base_dir / "chroma_db_prl27",
                        base_dir / "vector_db",
                        base_dir / "documents"
                    ]
                    config_file = base_dir / "config.json"
                    
                    # 1. Удаляем папки
                    for folder in folders_to_delete:
                        if folder.exists():
                            shutil.rmtree(folder)
                            print(f"[DEBUG] Удалена папка: {folder}", flush=True)
                    
                    # 2. Очищаем config.json
                    if config_file.exists():
                        with open(config_file, 'w', encoding='utf-8') as f:
                            json.dump({}, f)
                        print("[DEBUG] Config.json очищен", flush=True)
                    
                    # 3. Сбрасываем переменные в памяти
                    self.rag_system = None
                    
                    self._show_toast("Все данные успешно удалены! Перезапустите приложение.", color="#10b981", duration=5000)
                    
                except Exception as ex:
                    self._show_toast(f"Ошибка при очистке: {ex}", color="#ef4444", duration=4000)
            
            threading.Thread(target=run_clear, daemon=True).start()

        def cancel_clear(e):
            self.page.close(clear_dlg)

        clear_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Полная очистка данных", size=18, weight=ft.FontWeight.BOLD, color="#ef4444"),
            content=ft.Text(
                "Это действие необратимо!\n\n"
                "Будут удалены:\n"
                "• Вся векторная база знаний (ChromaDB)\n"
                "• Все загруженные пользовательские документы\n"
                "• Настройки путей к папкам\n\n"
                "Приложение вернется в состояние 'первого запуска'.",
                size=14,
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel_clear),
                ft.FilledButton(
                    "Да, удалить всё", 
                    on_click=confirm_clear,
                    style=ft.ButtonStyle(bgcolor="#ef4444", color="#ffffff"),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(clear_dlg)

    def _show_settings(self, e):
        model_dropdown = ft.Dropdown(
            options=[ft.dropdown.Option(k) for k in AVAILABLE_MODELS.keys()],
            value=self.current_model_display,
            width=300,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            label="Выберите модель",
        )
        status_lbl = ft.Text(f"Текущая: {self.current_model_display}", color=self.theme["status_ready"], size=12)

        def apply_model(e):
            chosen = model_dropdown.value
            print(f"[DEBUG] Выбрана модель: {chosen}", flush=True)
            if chosen and chosen in AVAILABLE_MODELS:
                self.current_model_display = chosen
                self.current_model_ollama = AVAILABLE_MODELS[chosen]
                self.model_label.value = f"{chosen}  •  PRL-27СМ RAG"
                self.rag_system = None
                status_lbl.value = f"Применена: {chosen}"
                print(f"[DEBUG] Модель установлена: {self.current_model_ollama}", flush=True)
                self.page.update()

        # ============================================
        # 1. Создаем диалог как атрибут класса (self.dlg)
        # ============================================
        self.dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Настройки", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("LLM Модель", size=14, weight=ft.FontWeight.BOLD),
                    model_dropdown,
                    status_lbl,
                ], tight=True, spacing=10),
                width=450,
                padding=20
            )
        )

        def apply_and_close(e):
            try:
                apply_model(e)
            except Exception as ex:
                print(f"[ERROR] apply_model: {ex}", flush=True)
            try:
                self.page.close(self.dlg)
            except Exception:
                pass
            self.page.update()

        # 2. Безопасно добавляем actions
        self.dlg.actions = [
                ft.FilledButton("Применить и закрыть", on_click=apply_and_close),
            ft.TextButton("Отмена", on_click=lambda e: self.page.close(self.dlg)),
        ]
        self.dlg.actions_alignment = ft.MainAxisAlignment.END

        # ============================================
        # БЛОК 1: Универсальная база знаний
        # ============================================
        self.kb_folder_path = ft.TextField(
            label="Путь к папке знаний",
            value=self._last_kb_path,          # <-- было "./knowledge_base"
            width=300,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
        )
        
        def choose_folder(e):
            self._open_folder_browser('kb')

        def sync_kb(e):
            folder = self.kb_folder_path.value.strip()
            if not folder:
                self._show_toast("Укажите путь к папке", color="#ef4444")
                return
            
            self._show_toast(f"Синхронизация: {folder}...", color="#f59e0b", duration=99999)
            
            def run_ingest():
                try:
                    from ingest_folder import ingest_folder
                    res = ingest_folder(folder, chat_id="global")
                    if res["success"] > 0:
                        self._show_toast(f"Добавлено {res['success']} из {res['total']} файлов", color="#10b981", duration=4000)
                    else:
                        self._show_toast(f"Не удалось добавить файлы. Проверьте консоль.", color="#ef4444", duration=4000)
                except Exception as ex:
                    self._show_toast(f"Ошибка синхронизации: {ex}", color="#ef4444", duration=4000)
            
            threading.Thread(target=run_ingest, daemon=True).start()

        sync_btn = ft.ElevatedButton(
            "Синхронизировать базу знаний",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=sync_kb,
            style=ft.ButtonStyle(bgcolor=self.theme["accent"], color="#ffffff"),
            width=float("inf"),
        )
        
        choose_btn = ft.IconButton(
            icon=ft.Icons.FOLDER,
            tooltip="Выбрать папку",
            on_click=choose_folder,
            style=ft.ButtonStyle(color=self.theme["text_primary"]),
        )

        # ============================================
        # БЛОК 2: База знаний PRL-27 
        # ============================================
        try:
            from config import settings as app_settings
            current_prl_path = getattr(app_settings, 'knowledge_base_path', '') or ''
        except:
            current_prl_path = ''
        
        self.prl_folder_path = ft.TextField(
            label="Путь к папке с документами PRL-27",
            value=self._last_prl_path or current_prl_path,   # <-- запомненный путь
            width=300,
            bgcolor=self.theme["bg_input"],
            color=self.theme["text_primary"],
            hint_text="Например: /Users/mihail/Documents/documents_ae",
        )
        
        def choose_prl_folder(e):
            self._open_folder_browser('prl')

        def rebuild_prl_index(e):
            if self.is_processing:
                self._show_toast("Процесс уже запущен, подождите завершения!", color="#f59e0b")
                return
            
            folder = self.prl_folder_path.value.strip()
            if not folder:
                self._show_toast("Укажите путь к папке", color="#ef4444")
                return
            
            if not Path(folder).exists():
                self._show_toast("Папка не существует!", color="#ef4444")
                return
            
            try:
                from config import settings as app_settings
                app_settings.knowledge_base_path = folder
                self._save_prl_path(folder)
                print(f"[DEBUG] Сохранён путь PRL: {folder}", flush=True)
            except Exception as ex:
                print(f"[WARN] Не удалось сохранить путь в конфиг: {ex}", flush=True)
            
            loading_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Обработка данных", weight=ft.FontWeight.BOLD),
                content=ft.Column([
                    ft.ProgressRing(width=48, height=48, stroke_width=5, color=self.theme["accent"]),
                    ft.Container(height=15),
                    ft.Text("Идет перестроение индекса PRL-27...\nЭто может занять около 1-2 минут.", text_align=ft.TextAlign.CENTER, size=14),
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                actions=[],
            )
            self.page.open(loading_dlg)
            self.page.update()
            
            def run_rebuild():
                try:
                    self.is_processing = True
                    print("[REBUILD] Поток запущен, импортирую модули...", flush=True)
                    
                    from data_ingestion import DocumentIngestor
                    print("[REBUILD] data_ingestion импортирован", flush=True)
                    
                    from vector_store import VectorStoreManager
                    print("[REBUILD] vector_store импортирован, начинаю сканирование...", flush=True)
                    
                    ingestor = DocumentIngestor(documents_path=folder)
                    documents = ingestor.process()
                    
                    if not documents:
                        self.page.run_thread(self._close_dialog_and_toast, loading_dlg,
                                             "Документы не найдены в папке!", "#ef4444", 4000)
                        self.is_processing = False
                        return
                    
                    print("[REBUILD] Создание векторной базы...", flush=True)
                    manager = VectorStoreManager()
                    manager.create(documents)
                    
                    self.page.run_thread(self._close_dialog_and_toast, loading_dlg,
                                          f"Индекс перестроен! {len(documents)} документов", "#10b981", 5000)
                    
                except Exception as ex:
                    import traceback
                    print(f"[ERROR] Ошибка перестроения: {ex}\n{traceback.format_exc()}", flush=True)
                    self.page.run_thread(self._close_dialog_and_toast, loading_dlg,
                                          f"Ошибка: {str(ex)[:60]}...", "#ef4444", 6000)
                finally:
                    self.is_processing = False
            
            # ЗАПУСКАЕМ перестроение в фоновом потоке
            threading.Thread(target=run_rebuild, daemon=True).start()

        rebuild_btn = ft.ElevatedButton(
            "Перестроить индекс PRL-27",
            icon=ft.Icons.BUILD,
            on_click=rebuild_prl_index,
            style=ft.ButtonStyle(bgcolor="#3b82f6", color="#ffffff"),
            width=float("inf"),
        )
        
        choose_prl_btn = ft.IconButton(
            icon=ft.Icons.FOLDER,
            tooltip="Выбрать папку PRL-27",
            on_click=choose_prl_folder,
            style=ft.ButtonStyle(color=self.theme["text_primary"]),
        )
        
        # ============================================
        # 3. Обновляем содержимое диалога всеми элементами
        # ============================================
        self.dlg.content = ft.Container(
            content=ft.Column([
                ft.Text("LLM Модель", size=14, weight=ft.FontWeight.BOLD),
                model_dropdown,
                status_lbl,
                ft.Divider(),
                ft.Text("База знаний PRL-27", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([self.prl_folder_path, choose_prl_btn], spacing=10),
                rebuild_btn,
                ft.Divider(),
                ft.Text("Универсальная база знаний", size=14, weight=ft.FontWeight.BOLD),
                ft.Row([self.kb_folder_path, choose_btn], spacing=10),
                sync_btn,
                ft.Divider(),
                ft.Text(f"Версия приложения: {APP_VERSION}", size=13, color=self.theme["text_secondary"]),
                ft.Divider(height=20, color="transparent"),
                ft.ElevatedButton(
                    "Полная очистка всех данных",
                    icon=ft.Icons.DELETE_FOREVER,
                    on_click=self._clear_all_data,
                    style=ft.ButtonStyle(bgcolor="#ef4444", color="#ffffff"),
                    width=float("inf"),
                ),
            ], tight=True, spacing=10),
            width=450,
            padding=20
        )
        
        self.page.open(self.dlg)

def main(page: ft.Page):
    AviationRAGApp(page)

if __name__ == "__main__":
    ft.app(target=main)