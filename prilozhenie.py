import json
import threading
from pathlib import Path
import sys
import platform
import re
import subprocess
from logging_config import setup_logging
setup_logging(level="INFO", log_file="logs/app.log")
import flet as ft
from logging_config import get_logger
logger = get_logger(__name__)

sys.path.append(str(Path(__file__).parent))
from smart_rag import SmartRAG
from vision import VisionAnalysisError
from jobs import JobController, RequestJob
from typing import Any, Callable
from activity import ActivityEvent
from ui_components import PALETTE, ActivityView, brand_icon, icon_button, welcome_panel
from assistant_identity import ASSISTANT_NAME

try:
    from document_processor import add_document, list_documents
except ImportError:
    add_document = None
    list_documents = None

THEME = PALETTE

APP_NAME = ASSISTANT_NAME
APP_VERSION = "1.0.0"
ASSETS_DIR = Path(__file__).parent / "assets"

from config import settings

AVAILABLE_MODELS = {
    settings.llm_model_name: settings.llm_model_name,
    "Qwen 2.5 (14B)": "qwen2.5:14b",
    "Qwen 2.5 VL (7B, изображения)": "qwen2.5vl:7b",
    "Qwen 2.5 Coder Abliterated (14B)": "huihui_ai/qwen2.5-coder-abliterate:14b",
    "Qwen 3 Abliterated (14B)": "huihui_ai/qwen3-abliterated:14b",
    "Qwen 3.5 Uncensored Aggressive (9B)": "fredrezones55/Qwen3.5-Uncensored-HauhauCS-Aggressive:9b",
    "Qwen 2.5 (7B)": "qwen2.5:7b",
    "Gemma 2 (9B)": "gemma2:9b",
}
DEFAULT_MODEL_DISPLAY = settings.llm_model_name

def load_assets():
    assets = {}
    logger.info(f"[ASSETS] Path: {ASSETS_DIR}")
    
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        assets["logo"] = str(logo_path)
    
    for name in ["assistant", "user"]:
        path = ASSETS_DIR / "avatars" / f"{name}.png"
        if path.exists():
            assets[name] = str(path)
    
    bg_path = ASSETS_DIR / "background.png"
    if bg_path.exists():
        assets["background"] = str(bg_path)
    
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        assets["icon"] = str(icon_path)
    
    return assets

from chat_store import ChatManager

class AviationRAGApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.theme = THEME
        self.assets = load_assets()
        self.current_model_display = DEFAULT_MODEL_DISPLAY
        self.current_model_local = AVAILABLE_MODELS[self.current_model_display]
        
        self.chat_manager = ChatManager()
        self._jobs = JobController()
        self.rag_system = None
        self.is_processing = False
        
        self.chat_list_controls = {}
        self.attachments_row = None  # Для хранения строки с чипами файлов
        
        self._wake_busy = False
        
        self.agent_mode = False
        
        self._streaming_chat_id = None
        self._streaming_row = None
        self._last_prl_path = self._load_prl_path()
        self._last_kb_path = "./knowledge_base"
        self._chat_file_contexts = {}  # chat_id -> текст последнего прикреплённого файла
        
        self._setup_page()
        self._build_ui()
        # АВТОМАТИЧЕСКИЙ ЗАПУСК wake-listener «Бутуз»
        try:
            from voice_input import WakeWordListener
            self.wake_listener = WakeWordListener(on_wake=self._on_wake_word)
            self.wake_listener.start()
            print("[VOICE] Wake-listener запущен автоматически", flush=True)
        except Exception as e:
            print(f"[VOICE] Не удалось запустить wake-listener: {e}", flush=True)
            self.wake_listener = None
        self.page.update()
        self._load_current_chat()
        
        self._voice_recording = False
        self._voice_busy = False
        self._voice_stop = None
        self.wake_listener = None
        
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
    
    def _extract_text_from_file(self, file_path: str) -> str:
        """Извлекает текст из файла (PDF, DOCX, TXT, MD)"""
        try:
            path = Path(file_path)
            suffix = path.suffix.lower()
            
            if suffix == '.txt' or suffix == '.md':
                return path.read_text(encoding='utf-8')
            
            elif suffix == '.pdf':
                import pdfplumber
                text = ""
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages[:10]:  # Первые 10 страниц
                        text += page.extract_text() or ""
                return text[:5000]  # Ограничиваем 5000 символов
            
            elif suffix == '.docx':
                from docx import Document
                doc = Document(path)
                return "\n".join([para.text for para in doc.paragraphs])[:5000]
            
            else:
                return ""
        except Exception as e:
            logger.error(f"Ошибка извлечения текста из {file_path}: {e}", exc_info=True)
            return ""
    
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

    def _show_file_approval_dialog(self, content: str, job: RequestJob) -> bool:
        from agent_files_ui import FileApproval
        return FileApproval(
            self.page, job,
            lambda: self._jobs.current is job and self.chat_manager.current_chat_id == job.chat_id,
        ).wait(content)

    def _set_activity(self, event: ActivityEvent) -> None:
        self.activity.apply(event)
        if hasattr(self, "send_button"):
            self.send_button.disabled = self.is_processing
            self.stop_button.visible = self.is_processing
        if not getattr(self, "_has_streamed_text", True) and hasattr(self, "_progress_text"):
            self._progress_text.value = event.detail or self.activity.text.value
            self._progress_ring.visible = self.activity.spinner.visible

    def _send_welcome_example(self, mode: str, text: str) -> None:
        self.agent_mode = mode == "AGENT"
        self.agent_checkbox.value = self.agent_mode
        self._send_example(text)

    def _handle_cancel_click(self, _: ft.ControlEvent) -> None:
        self._cancel_active_job()
        self._cleanup_cancelled_stream()
        self._set_activity(ActivityEvent("cancelled"))
        self.page.update()

    def _build_ui(self):
        self.chat_list_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=4)
        
        btn_accent_style = ft.ButtonStyle(
            bgcolor="#26384d", color="#ffffff", shape=ft.RoundedRectangleBorder(radius=10)
        )
        btn_text_style = ft.ButtonStyle(color=self.theme["text_primary"])
        
        self.sidebar = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Column([
                        # Логотип (icon.png) - увеличен и отцентрирован
                        ft.Container(
                            content=ft.Image(
                                src=self.assets["icon"] if "icon" in self.assets else self.assets.get("logo"),
                                height=90,
                                width=90,
                                fit=ft.ImageFit.CONTAIN,
                            ),
                            alignment=ft.alignment.center,  # Центрируем контейнер
                            width=float("inf"),  # Занимает всю ширину
                        ),
                        ft.Text(ASSISTANT_NAME, size=22, weight=ft.FontWeight.BOLD, color=self.theme["text_primary"], text_align=ft.TextAlign.CENTER),
                        ft.Text("Ваш локальный помощник", size=12, color=self.theme["text_secondary"], text_align=ft.TextAlign.CENTER),
                    ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.padding.symmetric(horizontal=16, vertical=20),
                    width=float("inf"),  # Контейнер на всю ширину сайдбара
                ),
                ft.Divider(height=1, color=self.theme["border"]),
                ft.ElevatedButton(
                    content=ft.Row([brand_icon("new_chat"), ft.Text("Новый чат", color="#e6edf7")],
                                   alignment=ft.MainAxisAlignment.CENTER, spacing=10, tight=True),
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
                            brand_icon("settings", 22),
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
        
        self.activity = ActivityView()
        self.status_text = self.activity.text
        self.model_label = ft.Text(
            self.current_model_display, size=12, color=self.theme["text_secondary"],
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
        )
        self.header = ft.Container(
            content=ft.Row([
                brand_icon("chat", 20), self.model_label, self.activity.control,
            ], spacing=10),
            padding=ft.padding.symmetric(horizontal=22, vertical=13),
        )

        self.messages_column = ft.Column([], scroll=ft.ScrollMode.AUTO, expand=True, spacing=12)
        
        self.welcome = welcome_panel(self._send_welcome_example)

        self.chat_stack = ft.Stack([self.welcome, self.messages_column], expand=True)
        
        self.chat_area = ft.Container(
            content=ft.Column([self.header, self.chat_stack], spacing=0),
            expand=True,
        )
        
        self.input_field = ft.TextField(
            hint_text="Напишите BUTUZIK.AI или прикрепите файл…",
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
        
        # FilePicker для выбора ПАПОК в настройках (обязателен)
        self.folder_picker = ft.FilePicker(on_result=self._on_folder_pick_result)
        self.page.overlay.append(self.folder_picker)
        self._folder_pick_target = None
        
        # FilePicker для файлов БОЛЬШЕ НЕ НУЖЕН:
        # прикрепление файлов теперь работает через встроенный браузер _open_file_browser()
        
        self.page.update()  # Обязательно обновляем страницу
        
        # ИСПРАВЛЕНО: Структура поля ввода теперь Column, чтобы чипы файлов были НАД строкой ввода
        self.attachments_row = ft.Row([], wrap=True, spacing=4, visible=False)
        
        # КНОПКА МИКРОФОНА (голосовой ввод)
        self.mic_button = icon_button(
            "mic", "Голосовой ввод: нажать для записи, ещё раз — завершить", self._toggle_voice_input,
        )

        # ЧЕКБОКС РЕЖИМА АГЕНТА
        self.agent_checkbox = ft.Checkbox(
            label="Режим агента",
            label_style=ft.TextStyle(size=13, weight=ft.FontWeight.NORMAL, color=self.theme["text_primary"]),
            width=190,
            value=False,
            active_color="#f59e0b",
            on_change=lambda e: setattr(self, 'agent_mode', e.control.value)
        )
        
        from agent_files_ui import AgentFilesUI
        self.agent_files = AgentFilesUI(
            self.page, lambda: self.chat_manager.current_chat_id,
            lambda message: self._show_toast(message),
        )
        self.files_button = ft.TextButton(
            content=ft.Row([brand_icon("files", 22), ft.Text("Файлы чата")], tight=True, spacing=7),
            width=155,
            on_click=self.agent_files.open,
            tooltip="Результаты агента: открыть папку или сохранить файл в удобное место",
        )

        self.send_button = icon_button("send", "Отправить сообщение", self._handle_send, primary=True)
        self.stop_button = icon_button("stop", "Остановить ответ", self._handle_cancel_click)
        self.stop_button.visible = False

        self.input_area = ft.Container(
            content=ft.Column([
                self.attachments_row,
                ft.Row([self.agent_checkbox, self.files_button], spacing=16, wrap=True),
                ft.Row([
                    self.mic_button,
                    icon_button("attach", "Прикрепить документ или изображение", self._handle_attach_click),
                    self.input_field,
                    self.stop_button,
                    self.send_button,
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

    def _image_to_base64(self, image_path: str) -> str:
        """Кодирует изображение в base64 для vision-модели"""
        import base64
        with open(image_path, 'rb') as f:
            return base64.b64encode(f.read()).decode('utf-8')

    def _get_image_mime(self, path: str) -> str:
        """Возвращает MIME-тип по расширению"""
        ext = Path(path).suffix.lower()
        return {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
        }.get(ext, 'image/jpeg')

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
        """Прикрепление файла к текущему сообщению"""
        logger.debug(f"Клик на кнопку +")
        # Используем встроенный браузер файлов
        self._open_file_browser()

    def _queue_job_ui(self, job: RequestJob, action: Callable[..., Any], *args: Any) -> None:
        def apply() -> None:
            if self.chat_manager.current_chat_id == job.chat_id:
                action(*args)
        self.page.run_thread(self._jobs.apply, job, apply)

    def _apply_activity(self, event: ActivityEvent) -> None:
        self._set_activity(event)
        self.page.update()

    def _queue_activity(self, job: RequestJob, event: ActivityEvent) -> None:
        # One page event loop preserves phase ordering; the job guard rejects late updates.
        async def apply() -> None:
            def update() -> None:
                if self.chat_manager.current_chat_id == job.chat_id:
                    self._apply_activity(event)
            self._jobs.apply(job, update)
        self.page.run_task(apply)

    def _complete_job(self, job: RequestJob, response: str, sources: list[str]) -> None:
        self._finalize_streaming_message(response, sources, job.chat_id)
        self._jobs.finish(job)

    def _fail_job(self, job: RequestJob, response: str,
                  retry_attachments: list[dict[str, str]]) -> None:
        if retry_attachments:
            pending = list(getattr(self, "_pending_attachments", []))
            existing = {item["path"] for item in pending}
            pending.extend(dict(item) for item in retry_attachments if item["path"] not in existing)
            self._pending_attachments = pending
            self._update_pending_attachments_display()
        self._complete_job(job, response, [])
        self._apply_activity(ActivityEvent("error", "Проверьте сообщение об ошибке"))

    def _cancel_active_job(self) -> None:
        self._jobs.cancel()
        self.is_processing = False
        self._set_activity(ActivityEvent("ready"))

    def _approve_for_job(self, job: RequestJob, content: str) -> bool:
        if job.token.get("cancelled") or self.chat_manager.current_chat_id != job.chat_id:
            return False
        self._queue_activity(job, ActivityEvent("approval", route="AGENT"))
        approved = self._show_file_approval_dialog(content, job)
        self._queue_activity(job, ActivityEvent("working", route="AGENT"))
        return approved

    def _process(self, user_input: str, attachments: list[dict[str, str]],
                 agent_mode: bool, job: RequestJob, model_name: str,
                 history: list[dict[str, Any]]) -> None:
        try:
            if job.token.get("cancelled"):
                return
            rag = self.rag_system
            if rag is None or rag.model_name != model_name:
                rag = SmartRAG(model_name=model_name)
                self._jobs.apply(job, lambda: setattr(self, "rag_system", rag))
            self._queue_job_ui(job, self._add_streaming_placeholder)
            user_context = ""
            file_notes = []
            for attachment in attachments:
                path = Path(attachment["path"])
                if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    from file_tools import prepare_attachments
                    prepare_attachments(job.chat_id, [attachment])
                    file_notes.append("attached/" + path.name)
                    text = self._extract_text_from_file(str(path))
                    if text:
                        user_context += f"\n[Прикреплённый файл: {path.name}]\n{text}\n"
            if user_context:
                self._chat_file_contexts[job.chat_id] = user_context
            if file_notes:
                user_input += "\nДоступные копии вложений: " + ", ".join(file_notes)

            def on_token(text: str) -> None:
                self._queue_job_ui(job, self._update_streaming_message, text)

            response, sources = rag.query_stream(
                user_input, chat_history=history, chat_id=job.chat_id,
                on_token=on_token, cancel_flag=job.token,
                user_context=user_context or None,
                recent_file_context=self._chat_file_contexts.get(job.chat_id),
                attachments=attachments, agent_mode=agent_mode,
                approve=lambda content: self._approve_for_job(job, content),
                on_activity=lambda event: self._queue_activity(job, event))
            if not job.token.get("cancelled"):
                self._queue_job_ui(job, self._complete_job, job, response, sources)
        except Exception as exc:
            logger.error("Request failed type=%s model=%s status=%s",
                         type(exc).__name__, model_name,
                         getattr(exc.__cause__ or exc, "status_code", "unknown"))
            if not job.token.get("cancelled"):
                self._queue_job_ui(job, self._fail_job, job, f"Ошибка: {exc}",
                                   attachments if isinstance(exc, VisionAnalysisError) else [])

    def _cleanup_cancelled_stream(self):
        """Очищает интерфейс, если стриминг был прерван удалением чата"""
        if hasattr(self, '_streaming_row') and self._streaming_row and self._streaming_row in self.messages_column.controls:
            self.messages_column.controls.remove(self._streaming_row)
        
        self.is_processing = False
        self._set_activity(ActivityEvent("ready"))
        self.page.update()

    def _update_pending_attachments_display(self):
        if not hasattr(self, '_pending_attachments'):
            self._pending_attachments = []
        
        self.attachments_row.controls.clear()
        
        if self._pending_attachments:
            for att in self._pending_attachments:
                path = Path(att['path'])
                is_image = path.suffix.lower() in ['.png', '.jpg', '.jpeg', '.webp']
                
                if is_image:
                    # Для картинок: chip с миниатюрой + имя файла
                    chip = ft.Container(
                        content=ft.Row([
                            ft.Image(
                                src=att['path'],  # Flet умеет подгружать по локальному пути
                                width=32, height=32,
                                fit=ft.ImageFit.COVER,
                                border_radius=4,
                            ),
                            ft.Text(att['name'], size=11, color="#dbeafe"),
                            ft.IconButton(
                                ft.Icons.CLOSE, icon_size=14,
                                on_click=lambda e, name=att['name']: self._remove_pending_attachment(name),
                                style=ft.ButtonStyle(color="#94a3b8", padding=0),
                            ),
                        ], spacing=6),
                        bgcolor="#1e3a8a",
                        padding=ft.padding.only(left=4, right=4, top=4, bottom=4),
                        border_radius=6,
                    )
                else:
                    # Для документов: обычный chip (как раньше)
                    chip = ft.Chip(
                        label=ft.Text(att['name'], size=11, color="#dbeafe"),
                        bgcolor="#1e3a8a", padding=4,
                        delete_icon=ft.Icon(ft.Icons.CLOSE, size=14, color="#94a3b8"),
                        on_delete=lambda e, name=att['name']: self._remove_pending_attachment(name),
                    )
                
                self.attachments_row.controls.append(chip)
            self.attachments_row.visible = True
        else:
            self.attachments_row.visible = False
        
        self.page.update()
        
    def _remove_pending_attachment(self, filename):
        """Удаляет файл из списка ожидающих прикрепления"""
        if hasattr(self, '_pending_attachments'):
            self._pending_attachments = [
                att for att in self._pending_attachments 
                if att['name'] != filename
            ]
            self._update_pending_attachments_display()

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

    def _open_file_browser(self):
        """Встроенный браузер файлов (работает гарантированно, без системных диалогов)"""
        # Стартовая папка: домашняя директория
        start = str(Path.home())
        
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
            
            # Показываем файлы (а не только папки)
            try:
                items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except Exception:
                items = []
            
            # Сначала папки
            for item in items:
                if item.is_dir() and not item.name.startswith('.'):
                    list_column.controls.append(
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.FOLDER, size=18, color=self.theme["accent"]),
                                ft.Text(item.name, size=13, color=self.theme["text_primary"]),
                            ], spacing=8),
                            padding=ft.padding.symmetric(horizontal=8, vertical=6),
                            border_radius=6,
                            ink=True,
                            on_click=lambda e, dd=item: (setattr(path_field, 'value', str(dd)), refresh()),
                        )
                    )
            
            # Потом файлы
            CODE_EXTS = ['.py', '.cpp', '.c', '.h', '.hpp', '.js', '.ts', '.sh', '.json', '.xml', '.ini', '.cfg']
            allowed_exts = ['.pdf', '.docx', '.txt', '.md', '.png', '.jpg', '.jpeg', '.webp'] + CODE_EXTS
            files_found = 0
            
            for item in items:
                if item.is_file():
                    ext = item.suffix.lower()
                    if ext in allowed_exts:
                        files_found += 1
                        list_column.controls.append(
                            ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.IMAGE if ext in {'.png', '.jpg', '.jpeg', '.webp'} else ft.Icons.DESCRIPTION, 
                                            size=18, color="#60a5fa"),
                                    ft.Text(item.name, size=13, color=self.theme["text_primary"]),
                                ], spacing=8),
                                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                                border_radius=6,
                                ink=True,
                                on_click=lambda e, ff=item: self._select_file(str(ff), ff.name),
                            )
                        )
            
            print(f"[DEBUG] В папке {p.name} найдено {files_found} разрешённых файлов", flush=True)
            
            if not items or (len(items) == files_found and files_found == 0):
                list_column.controls.append(
                    ft.Text("(нет файлов или папок для отображения)", size=12, color=self.theme["text_secondary"])
                )
            
            if not items:
                list_column.controls.append(
                    ft.Text("(папка пуста)", size=12, color=self.theme["text_secondary"])
                )
            self.page.update()
        
        path_field.on_submit = lambda e: refresh()
        
        def go_up(e):
            p = Path(path_field.value).expanduser().parent
            path_field.value = str(p)
            refresh()
        
        def cancel(e):
            self.page.close(browser_dlg)
        
        # Получаем размеры окна приложения
        win_w = self.page.window.width or 1200
        win_h = self.page.window.height or 800
        
        browser_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Выбор файла", size=18, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.IconButton(ft.Icons.ARROW_UPWARD, tooltip="Вверх", on_click=go_up),
                        path_field,
                    ], spacing=6),
                    ft.Text("Клик по папке — войти. Клик по файлу — выбрать.",
                            size=11, color=self.theme["text_secondary"]),
                    ft.Divider(height=1),
                    ft.Container(content=list_column, expand=True),  # expand вместо height=400
                ], spacing=8, expand=True),  # expand для внешней колонки
                width=min(900, int(win_w * 0.8)),    # 80% ширины окна (макс 900px)
                height=min(650, int(win_h * 0.75)),  # 75% высоты окна (макс 650px)
            ),
            actions=[
                ft.TextButton("Отмена", on_click=cancel),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        refresh()
        self.page.open(browser_dlg)
    
    def _select_file(self, file_path: str, file_name: str):
        """Обработчик выбора файла в браузере"""
        print(f"[DEBUG] Выбран файл: {file_name}", flush=True)
        
        # Закрываем браузер
        # browser_dlg доступен из замыкания, но нам нужно его закрыть
        # Для этого найдём его в overlay страницы
        for overlay in self.page.overlay:
            if isinstance(overlay, ft.AlertDialog) and overlay.title and "Выбор файла" in (overlay.title.value if hasattr(overlay.title, 'value') else ""):
                self.page.close(overlay)
                break
        
        # Добавляем файл в pending_attachments
        if not hasattr(self, '_pending_attachments'):
            self._pending_attachments = []
        
        # Проверяем, не добавлен ли уже
        if any(att['name'] == file_name for att in self._pending_attachments):
            self._show_toast(f"Файл '{file_name}' уже прикреплён", color="#f59e0b")
            return
        
        self._pending_attachments.append({
            'path': file_path,
            'name': file_name,
        })
        
        self._update_pending_attachments_display()
        self._show_toast(f"Прикреплён: {file_name}", color="#10b981")

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
                        content=ft.Text(name, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                        color=self.theme["text_primary"]),
                        expand=True,
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    ),
                    icon_button("delete", "Удалить чат",
                                lambda e, cid=chat_id: self._delete_chat(cid), size=20),
                ],
                spacing=0,
            )
            
            # Обертка для клика по всей строке
            chat_container = ft.Container(
                content=chat_row,
                bgcolor="#213952" if is_current else None,
                border=ft.border.all(1, "#426480") if is_current else None,
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
            self._jobs.cancel()
            print(f"[DELETE] Останавливаем генерацию при удалении чата", flush=True)
            if hasattr(self, '_stream_cancel_flag'):
                self._stream_cancel_flag["cancelled"] = True
            
            if hasattr(self, '_streaming_row') and self._streaming_row in self.messages_column.controls:
                self.messages_column.controls.remove(self._streaming_row)
            
            self.is_processing = False
            self._set_activity(ActivityEvent("ready"))
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
        self._cancel_active_job()
        self.chat_manager.create_new_chat()
        self._update_chat_list()
        self._load_current_chat()

    def _switch_chat(self, chat_id):
        self._cancel_active_job()
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
            self._set_activity(ActivityEvent("ready"))
            self.page.update()
        
        # Теперь переключаемся
        self.chat_manager.switch_chat(chat_id)
        self._update_chat_list()
        self._load_current_chat()

    def _load_current_chat(self):
        chat = self.chat_manager.get_current_chat()
        self.messages_column.controls.clear()
        self.messages_column.visible = bool(chat and chat["messages"])

        if chat and chat["messages"]:
            self.welcome.visible = False
            self.messages_column.visible = True
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
                short_names = [s[:40] + "..." if len(s) > 40 else s for s in sources[:3]]
                source_text = "📎 Источники: " + ", ".join(short_names)
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
        self.messages_column.visible = True
        self.page.update()
        self.messages_column.scroll_to(offset=-1, duration=300)

    def _handle_send(self, e):
        text = self.input_field.value.strip()
        if not text or self.is_processing:
            if self.is_processing:
                self._show_toast("⏳ Подождите завершения текущего ответа!", color="#f59e0b")
            return
        
        # Получаем прикреплённые файлы
        pending_attachments = getattr(self, '_pending_attachments', [])
        
        self.input_field.value = ""
        self._pending_attachments = []  # Очищаем список прикреплённых файлов
        self._update_pending_attachments_display()
        
        chat = self.chat_manager.get_current_chat()
        if chat and chat["name"] == "Новый чат" and len(chat["messages"]) == 0:
            new_name = text[:30] + ("..." if len(text) > 30 else "")
            self.chat_manager.rename_chat(self.chat_manager.current_chat_id, new_name)
            self._update_chat_list()
        
        # Формируем список имён файлов для отображения
        attachment_names = [att['name'] for att in pending_attachments]
        
        self._add_message_to_ui("user", text, attachments=attachment_names)
        self.chat_manager.add_message("user", text, attachments=attachment_names)
        
        self.is_processing = True
        self._set_activity(ActivityEvent("thinking"))
        self.page.update()
        
        chat_id = self.chat_manager.current_chat_id
        job = self._jobs.start(chat_id)
        self._stream_cancel_flag = job.token
        self._streaming_chat_id = chat_id
        history = (self.chat_manager.get_current_chat() or {}).get("messages", [])[:-1][-8:]
        threading.Thread(
            target=self._process,
            args=(text, pending_attachments, self.agent_mode, job, self.current_model_local, history),
            daemon=True
        ).start()

    # ============ ГОЛОСОВОЙ ВВОД ============
    
    def _set_mic_state(self, state):
        if state == "rec":
            self.mic_button.content = brand_icon("stop")
        elif state == "busy":
            self.mic_button.content = brand_icon("chat")
        else:
            self.mic_button.content = brand_icon("mic")
        self.mic_button.update()
    
    def _toggle_voice_input(self, e):
        if self._voice_busy:
            return
        if not self._voice_recording:
            import threading as _th
            self._voice_stop = _th.Event()
            self._voice_recording = True
            self._set_mic_state("rec")
            self._show_toast("Запись... нажмите ещё раз, чтобы завершить", color="#3b82f6", duration=2500)
            _th.Thread(target=self._voice_record_loop, daemon=True).start()
        else:
            self._voice_stop.set()
    
    def _voice_record_loop(self):
        try:
            from voice_input import record_until_stop, transcribe
            audio = record_until_stop(self._voice_stop)
            self._voice_recording = False
            self.page.run_thread(self._set_mic_state, "busy")
            self.page.run_thread(self._show_toast, "Распознаю речь (первый запуск может грузить модель)...", "#f59e0b", 4000)
            text = transcribe(audio)
            self.page.run_thread(self._voice_apply_text, text)
        except Exception as ex:
            logger.error(f"[VOICE] Ошибка записи: {ex}", exc_info=True)
            self._voice_recording = False
            self.page.run_thread(self._set_mic_state, "idle")
            self.page.run_thread(self._show_toast, f"Ошибка микрофона: {ex}", "#ef4444")
    
    def _voice_apply_text(self, text):
        self._set_mic_state("idle")
        text = (text or "").strip()
        if not text:
            self._show_toast("Не удалось распознать речь", color="#ef4444")
            return
        self.input_field.value = ((self.input_field.value or "") + " " + text).strip()
        self.input_field.update()
        self._show_toast(f"Распознано: {text[:60]}", color="#10b981")
    
    # ---- Wake-word «Бутуз» ----
    
    def _start_wake_listener(self):
        from voice_input import WakeWordListener
        if self.wake_listener is None or not self.wake_listener.is_alive():
            self.wake_listener = WakeWordListener(on_wake=self._on_wake_word)
        self.wake_listener.start()
        self._show_toast("Слежу за «Бутуз»...", color="#3b82f6")
    
    def _stop_wake_listener(self):
        if self.wake_listener:
            self.wake_listener.stop()
    
    def _on_wake_word(self):
        """Вызывается ИЗ ПОТОКА СЛУШАТЕЛЯ — паузу ставим сразу, без задержек"""
        if self._voice_recording or self._voice_busy or self._wake_busy:
            return
        self._wake_busy = True
        if self.wake_listener:
            self.wake_listener.paused.set()   # мгновенно, в этом же потоке
        self.page.run_thread(self._wake_ui)
    
    def _wake_ui(self):
        try:
            import subprocess
            subprocess.Popen(['afplay', '/System/Library/Sounds/Glass.aiff'])  # 🔔 ding!
        except Exception:
            pass
        self._show_toast("🐶 Бутуз слушает! Говорите команду...", color="#f59e0b", duration=3000)
        if self.wake_listener:
            self.wake_listener.paused.set()
        import threading as _th
        _th.Thread(target=self._wake_command_loop, daemon=True).start()
    
    def _wake_command_loop(self):
        try:
            import time as _time
            from voice_input import record_until_silence, transcribe, WAKE_WORDS, _fuzzy_match
            _time.sleep(1.0)  # даём слову «Бутуз» полностью отзвучать
            audio = record_until_silence()
            text = transcribe(audio)
            
            # Если поймали хвост wake-слова или огрызок — слушаем ещё раз
            if text and (_fuzzy_match(text, WAKE_WORDS) or len(text.strip()) < 4):
                print(f"[VOICE] Пойман хвост wake-слова: '{text}' — слушаю команду заново", flush=True)
                self.page.run_thread(self._show_toast, "🐶 Слушаю! Скажи команду...", "#f59e0b", 2500)
                audio = record_until_silence()
                text = transcribe(audio)
            
            self.page.run_thread(self._wake_apply, text)
        except Exception as ex:
            print(f"[VOICE] Ошибка wake-команды: {ex}", flush=True)
            self.page.run_thread(self._wake_apply, "")
    
    def _wake_apply(self, text):
        if self.wake_listener:
            self.wake_listener.paused.clear()
        self._wake_busy = False
        
        text = (text or "").strip().lower()
        
        # 1. Убираем слова-паразиты, которые сбивают роутер
        for filler in ["слушай", "ну", "эм", "ээ", "короче", "так", "вот"]:
            text = text.replace(filler, "").strip()
        
        # Убираем лишние пробелы и знаки препинания в начале
        text = text.lstrip(".,!?;: ").capitalize()
        
        #  2. Никогда не отправляем wake-слово или пустоту
        if not text or len(text) < 4:
            self._show_toast("Не расслышал команду 🙁", color="#ef4444")
            return
            
        try:
            from voice_input import WAKE_WORDS, _fuzzy_match
            if _fuzzy_match(text.lower(), WAKE_WORDS):
                self._show_toast("Это было будильное слово 😄", color="#f59e0b")
                return
        except Exception:
            pass
        
        # 3. Если вопрос короткий и технический, делаем его более формальным для роутера
        if "pps" in text.lower() or "ппс" in text.lower() or "сигнал" in text.lower():
            if not text.lower().startswith(("что такое", "как", "расскажи")):
                text = "Что такое " + text
        
        self.input_field.value = text
        self.input_field.update()
        self._show_toast(f"🐶 Команда: {text[:60]}", color="#10b981")
        self._handle_send(None)
    
    def _on_wake_switch(self, e):
        if e.control.value:
            if self.wake_listener is None or not self.wake_listener.is_alive():
                self._start_wake_listener()
            else:
                self._show_toast("Уже слушает «Бутуз»", color="#10b981")
        else:
            self._stop_wake_listener()

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
                info["chat_id"] = chat_id
                self.page.run_thread(self._on_document_ready, info)
            else:
                self.page.run_thread(self._on_document_ready, {"error": "Модуль document_processor не найден"})
        except Exception as e:
            import traceback
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
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
            
            self.chat_manager.add_attachment(info["filename"], chat_id=info.get("chat_id"))
        
        if not self.is_processing:
            self._set_activity(ActivityEvent("ready"))
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
                self.chat_manager.remove_attachment(filename)
                
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
        self._has_streamed_text = False
        self._progress_text = ft.Text(self.activity.text.value, size=13, color=self.theme["text_secondary"])
        self._progress_ring = ft.ProgressRing(width=14, height=14, stroke_width=2, color="#9edcf2")
        progress = ft.Row([
            self._progress_ring, self._progress_text,
        ], spacing=10)

        self._streaming_bubble = ft.Container(
            content=progress,
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
        self.messages_column.visible = True
        self.page.update()
        self.messages_column.scroll_to(offset=-1, duration=100)
    
    def _update_streaming_message(self, text):
        """Обновляет текст streaming-сообщения с кнопками копирования кода"""
        if hasattr(self, '_streaming_bubble') and self._streaming_bubble:
            self._has_streamed_text = True
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
        self.chat_manager.add_message("assistant", response, sources=sources, chat_id=target_chat_id)
        
        self.is_processing = False
        self._set_activity(ActivityEvent("ready"))
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
        self._set_activity(ActivityEvent("ready"))
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
        wake_switch = ft.Switch(
            label="Голосовая активация «Бутуз»",
            value=self.wake_listener is not None and self.wake_listener.is_alive(),
            active_color=self.theme["accent"],
            on_change=self._on_wake_switch,
        )
        
        status_lbl = ft.Text(f"Текущая: {self.current_model_display}", color=self.theme["status_ready"], size=12)

        def apply_model(e):
            chosen = model_dropdown.value
            print(f"[DEBUG] Выбрана модель: {chosen}", flush=True)
            if chosen and chosen in AVAILABLE_MODELS:
                self.current_model_display = chosen
                self.current_model_local = AVAILABLE_MODELS[chosen]
                self.model_label.value = chosen
                self.rag_system = None
                status_lbl.value = f"Применена: {chosen}"
                print(f"[DEBUG] Модель установлена: {self.current_model_local}", flush=True)
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
                wake_switch,
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
