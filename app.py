import customtkinter as ctk
from tkinter import messagebox
import json
import threading
from pathlib import Path
import sys
from PIL import Image

sys.path.append(str(Path(__file__).parent))
from smart_rag import SmartRAG

# ==========================================
# ЦВЕТОВАЯ ПАЛИТРА
# ==========================================
THEMES = {
    "dark": {
        "bg_main": "#212121",
        "bg_sidebar": "#171717",
        "bg_input": "#2f2f2f",
        "bg_bubble_user": "#3b82f6",
        "bg_bubble_ai": "#2f2f2f",
        "text_primary": "#ececec",
        "text_secondary": "#8e8e8e",
        "accent": "#10a37f",
        "accent_hover": "#0d8c6d",
        "border": "#424242",
        "btn_text": "#ececec",
    },
    "light": {
        "bg_main": "#ffffff",
        "bg_sidebar": "#f0f0f0",
        "bg_input": "#f7f7f8",
        "bg_bubble_user": "#3b82f6",
        "bg_bubble_ai": "#f4f4f4",
        "text_primary": "#1a1a1a",
        "text_secondary": "#6b6b6b",
        "accent": "#10a37f",
        "accent_hover": "#0d8c6d",
        "border": "#d9d9e3",
        "btn_text": "#1a1a1a",
    }
}

APP_NAME = "Aviation RAG-System"
APP_VERSION = "1.0.0"
CHATS_FILE = "chats_history.json"
ASSETS_DIR = Path("assets")


# ==========================================
# ЗАГРУЗКА ИЗОБРАЖЕНИЙ
# ==========================================
def find_image(base_path: Path) -> Path | None:
    """Ищет изображение с возможным двойным расширением"""
    if base_path.exists():
        return base_path
    
    alt_path = Path(str(base_path) + ".jpg")
    if alt_path.exists():
        return alt_path
    
    if base_path.suffix:
        for ext in [".jpg", ".png", ".jpeg"]:
            alt = base_path.with_suffix(ext)
            if alt.exists():
                return alt
    
    return None


def load_image_safe(image_path: Path, size: tuple) -> ctk.CTkImage | None:
    """Безопасная загрузка изображения"""
    actual_path = find_image(image_path)
    if actual_path:
        try:
            img = Image.open(actual_path).convert("RGBA")
            img = img.resize(size, Image.LANCZOS)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception as e:
            print(f"Ошибка загрузки {actual_path}: {e}")
    return None


# ==========================================
# МЕНЕДЖЕР ЧАТОВ
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
    
    def add_message(self, role: str, content: str):
        chat = self.get_current_chat()
        if chat:
            chat["messages"].append({"role": role, "content": content})
            self.save()
    
    def switch_chat(self, chat_id: str):
        if chat_id in self.chats:
            self.current_chat_id = chat_id


# ==========================================
# ДИАЛОГ ПЕРЕИМЕНОВАНИЯ (собственное окно)
# ==========================================
class RenameDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, initial_value: str, callback, theme: str = "dark"):
        super().__init__(parent)
        self.callback = callback
        self.colors = THEMES[theme]
        
        self.title(title)
        self.geometry("400x180")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=self.colors["bg_sidebar"])
        
        # Центрируем относительно родителя
        self.transient(parent)
        
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack(pady=20)
        
        self.entry = ctk.CTkEntry(
            self,
            width=320,
            height=40,
            font=ctk.CTkFont(size=14),
            fg_color=self.colors["bg_input"],
            text_color=self.colors["text_primary"],
            border_color=self.colors["border"],
            corner_radius=8
        )
        self.entry.pack(pady=10)
        self.entry.insert(0, initial_value)
        self.entry.focus_set()
        self.entry.select_range(0, "end")
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=15)
        
        ctk.CTkButton(
            btn_frame,
            text="Отмена",
            command=self.destroy,
            width=100,
            height=35,
            fg_color="transparent",
            border_width=1,
            border_color=self.colors["border"],
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=10)
        
        ctk.CTkButton(
            btn_frame,
            text="Сохранить",
            command=self._save,
            width=100,
            height=35,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=10)
        
        self.entry.bind("<Return>", lambda e: self._save())
        self.entry.bind("<Escape>", lambda e: self.destroy())
    
    def _save(self):
        new_name = self.entry.get().strip()
        if new_name:
            self.callback(new_name)
        self.destroy()


# ==========================================
# ДИАЛОГ ПОДТВЕРЖДЕНИЯ
# ==========================================
class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, message: str, callback, theme: str = "dark"):
        super().__init__(parent)
        self.callback = callback
        self.colors = THEMES[theme]
        
        self.title(title)
        self.geometry("380x180")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=self.colors["bg_sidebar"])
        self.transient(parent)
        
        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack(pady=20)
        
        ctk.CTkLabel(
            self,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=self.colors["text_secondary"]
        ).pack(pady=5)
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)
        
        ctk.CTkButton(
            btn_frame,
            text="Отмена",
            command=self.destroy,
            width=100,
            height=35,
            fg_color="transparent",
            border_width=1,
            border_color=self.colors["border"],
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=13)
        ).pack(side="left", padx=10)
        
        ctk.CTkButton(
            btn_frame,
            text="Удалить",
            command=lambda: self._confirm(True),
            width=100,
            height=35,
            fg_color="#dc2626",
            hover_color="#991b1b",
            text_color="#ffffff",
            font=ctk.CTkFont(size=13, weight="bold")
        ).pack(side="left", padx=10)
    
    def _confirm(self, result):
        self.callback(result)
        self.destroy()


# ==========================================
# БОКОВАЯ ПАНЕЛЬ
# ==========================================
class Sidebar(ctk.CTkFrame):
    def __init__(self, master, chat_manager: ChatManager, theme: str = "dark", assets: dict = None, **kwargs):
        super().__init__(master, width=260, corner_radius=0, **kwargs)
        self.chat_manager = chat_manager
        self.theme = theme
        self.colors = THEMES[theme]
        self.assets = assets or {}
        self.app_ref = None  # Ссылка на главное приложение
        
        self.grid_propagate(False)
        self.grid_rowconfigure(3, weight=1)
        
        self._build_ui()
        self.update_chat_list()
    
    def set_app_ref(self, app):
        self.app_ref = app
    
    def _build_ui(self):
        # Заголовок
        header = ctk.CTkFrame(self, fg_color="transparent", height=80)
        header.grid(row=0, column=0, padx=12, pady=15, sticky="ew")
        header.grid_propagate(False)
        
        if "logo" in self.assets:
            ctk.CTkLabel(header, image=self.assets["logo"], text="").pack(pady=(0, 5))
        
        ctk.CTkLabel(
            header,
            text="Aviation RAG",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack()
        
        # Кнопка "Новый чат"
        new_chat_icon = self.assets.get("new_chat")
        self.new_chat_btn = ctk.CTkButton(
            self,
            text="Новый чат",
            image=new_chat_icon,
            command=self._handle_new_chat,
            height=40,
            fg_color="transparent",
            border_width=1,
            border_color=self.colors["border"],
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=13),
            anchor="w",
            corner_radius=8,
            compound="left"
        )
        self.new_chat_btn.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        
        # Разделитель
        ctk.CTkFrame(self, height=1, fg_color=self.colors["border"]).grid(
            row=2, column=0, padx=12, pady=8, sticky="ew"
        )
        
        # Список чатов
        self.chat_list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=self.colors["border"],
            scrollbar_button_hover_color="#555555"
        )
        self.chat_list_frame.grid(row=3, column=0, padx=8, pady=4, sticky="nsew")
        
        # Нижняя панель
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, padx=12, pady=12, sticky="ew")
        
        self.theme_btn = ctk.CTkButton(
            bottom,
            text="Светлая тема" if self.theme == "dark" else "Тёмная тема",
            command=self._handle_theme_toggle,
            height=36,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=11),
            anchor="w",
            corner_radius=8
        )
        self.theme_btn.pack(fill="x", pady=2)
        
        clear_icon = self.assets.get("clear")
        self.delete_btn = ctk.CTkButton(
            bottom,
            text="Удалить чат",
            image=clear_icon,
            command=self._handle_delete_current,
            height=36,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=11),
            anchor="w",
            corner_radius=8,
            compound="left"
        )
        self.delete_btn.pack(fill="x", pady=2)
        
        settings_icon = self.assets.get("settings")
        self.settings_btn = ctk.CTkButton(
            bottom,
            text="Настройки",
            image=settings_icon,
            command=self._handle_settings,
            height=36,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=11),
            anchor="w",
            corner_radius=8,
            compound="left"
        )
        self.settings_btn.pack(fill="x", pady=2)
    
    def _handle_new_chat(self):
        if self.app_ref:
            self.app_ref._new_chat()
    
    def _handle_theme_toggle(self):
        if self.app_ref:
            self.app_ref._toggle_theme()
    
    def _handle_delete_current(self):
        if self.chat_manager.current_chat_id and self.app_ref:
            self.app_ref._delete_chat(self.chat_manager.current_chat_id)
    
    def _handle_settings(self):
        if self.app_ref:
            self.app_ref._show_settings()
    
    def update_chat_list(self):
        for widget in self.chat_list_frame.winfo_children():
            widget.destroy()
        
        for chat_id, chat_data in reversed(list(self.chat_manager.chats.items())):
            is_current = chat_id == self.chat_manager.current_chat_id
            
            btn = ctk.CTkButton(
                self.chat_list_frame,
                text=f"  {chat_data['name'][:25]}{'...' if len(chat_data['name']) > 25 else ''}",
                command=lambda cid=chat_id: self._handle_switch(cid),
                height=38,
                anchor="w",
                fg_color=self.colors["accent"] if is_current else "transparent",
                hover_color=self.colors["bg_input"],
                text_color=self.colors["btn_text"],
                font=ctk.CTkFont(size=12),
                corner_radius=8
            )
            btn.pack(fill="x", pady=2)
            btn.bind("<Button-3>", lambda e, cid=chat_id: self._show_context_menu(e, cid))
    
    def _handle_switch(self, chat_id):
        if self.app_ref:
            self.app_ref._switch_chat(chat_id)
    
    def _show_context_menu(self, event, chat_id):
        menu = ctk.CTkToplevel(self)
        menu.title("Меню")
        menu.geometry("200x100")
        menu.resizable(False, False)
        menu.attributes("-topmost", True)
        menu.configure(fg_color=self.colors["bg_sidebar"])
        menu.transient(self)
        
        x = self.winfo_pointerx()
        y = self.winfo_pointery()
        menu.geometry(f"+{x}+{y}")
        
        ctk.CTkButton(
            menu,
            text="Переименовать",
            command=lambda: self._handle_rename(chat_id, menu),
            height=35,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"]
        ).pack(fill="x", padx=8, pady=4)
        
        ctk.CTkButton(
            menu,
            text="Удалить",
            command=lambda: self._handle_delete(chat_id, menu),
            height=35,
            fg_color="#dc2626",
            hover_color="#991b1b",
            text_color="#ffffff"
        ).pack(fill="x", padx=8, pady=4)
    
    def _handle_rename(self, chat_id, menu):
        menu.destroy()
        if self.app_ref:
            self.app_ref._rename_chat(chat_id)
    
    def _handle_delete(self, chat_id, menu):
        menu.destroy()
        if self.app_ref:
            self.app_ref._delete_chat(chat_id)
    
    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = THEMES[theme]
        self.configure(fg_color=self.colors["bg_sidebar"])
        self.new_chat_btn.configure(
            border_color=self.colors["border"],
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"]
        )
        self.theme_btn.configure(
            text="Тёмная тема" if theme == "dark" else "Светлая тема",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"]
        )
        self.delete_btn.configure(
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"]
        )
        self.settings_btn.configure(
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"]
        )
        self.update_chat_list()


# ==========================================
# ОБЛАСТЬ ЧАТА
# ==========================================
class ChatArea(ctk.CTkFrame):
    def __init__(self, master, theme: str = "dark", assets: dict = None, **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)
        self.theme = theme
        self.colors = THEMES[theme]
        self.assets = assets or {}
        
        # Используем pack вместо grid для надёжности
        self._build_header()
        self._build_welcome()
        self._build_messages()
        
        # По умолчанию показываем приветствие
        self.welcome_frame.pack(fill="both", expand=True)
    
    def _build_header(self):
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=50)
        self.header.pack(fill="x", padx=20, pady=10)
        self.header.pack_propagate(False)
        
        self.model_label = ctk.CTkLabel(
            self.header,
            text="Gemma2 9B  •  PRL-27СМ RAG",
            font=ctk.CTkFont(size=13),
            text_color=self.colors["text_secondary"]
        )
        self.model_label.pack(side="left")
        
        self.status_label = ctk.CTkLabel(
            self.header,
            text="● Готов",
            font=ctk.CTkFont(size=12),
            text_color="#10a37f"
        )
        self.status_label.pack(side="right")
    
    def _build_welcome(self):
        self.welcome_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        content = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
        content.pack(expand=True)
        
        if "logo" in self.assets:
            ctk.CTkLabel(content, image=self.assets["logo"], text="").pack(pady=(0, 20))
        else:
            ctk.CTkLabel(content, text="✈️", font=ctk.CTkFont(size=60)).pack(pady=(0, 20))
        
        ctk.CTkLabel(
            content,
            text="Чем могу помочь?",
            font=ctk.CTkFont(size=28, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack(pady=(0, 8))
        
        ctk.CTkLabel(
            content,
            text="Задайте вопрос по документации ПРЛ-27СМ",
            font=ctk.CTkFont(size=14),
            text_color=self.colors["text_secondary"]
        ).pack(pady=(0, 40))
        
        examples = [
            "Как включить излучение шкафа 276ГГ02?",
            "Что такое сигнал PPS?",
            "Какие параметры опрашивает МКУ?",
            "Протокол взаимодействия МКУ-УМИ",
        ]
        
        grid = ctk.CTkFrame(content, fg_color="transparent")
        grid.pack()
        
        for i, text in enumerate(examples):
            btn = ctk.CTkButton(
                grid,
                text=text,
                height=50,
                width=280,
                fg_color=self.colors["bg_input"],
                hover_color=self.colors["border"],
                border_width=1,
                border_color=self.colors["border"],
                text_color=self.colors["text_primary"],
                font=ctk.CTkFont(size=13),
                corner_radius=10,
                anchor="w"
            )
            btn.grid(row=i//2, column=i%2, padx=8, pady=6, sticky="ew")
    
    def _build_messages(self):
        self.messages_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=self.colors["bg_main"],
            scrollbar_button_color=self.colors["border"],
            scrollbar_button_hover_color="#555555"
        )
        # Не pack'им сразу
    
    def show_welcome(self):
        if self.messages_frame.winfo_manager():
            self.messages_frame.pack_forget()
        self.welcome_frame.pack(fill="both", expand=True)
    
    def show_messages(self):
        if self.welcome_frame.winfo_manager():
            self.welcome_frame.pack_forget()
        self.messages_frame.pack(fill="both", expand=True)
    
    def clear_messages(self):
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
    
    def add_message(self, role: str, content: str):
        outer = ctk.CTkFrame(self.messages_frame, fg_color="transparent")
        outer.pack(fill="x", pady=8)
        
        if role == "user":
            row = ctk.CTkFrame(outer, fg_color="transparent")
            row.pack(side="right")
            
            bubble = ctk.CTkFrame(
                row,
                fg_color=self.colors["bg_bubble_user"],
                corner_radius=18
            )
            bubble.pack(side="left", padx=(10, 0))
            
            ctk.CTkLabel(
                bubble,
                text=content,
                wraplength=700,
                justify="left",
                text_color="#ffffff",
                font=ctk.CTkFont(size=14),
                padx=16,
                pady=12
            ).pack()
            
            if "user" in self.assets:
                ctk.CTkLabel(row, image=self.assets["user"], text="").pack(side="right", padx=(10, 0))
            else:
                ctk.CTkLabel(row, text="👤", font=ctk.CTkFont(size=24)).pack(side="right", padx=(10, 0))
        
        else:
            row = ctk.CTkFrame(outer, fg_color="transparent")
            row.pack(side="left", fill="x")
            
            if "assistant" in self.assets:
                ctk.CTkLabel(row, image=self.assets["assistant"], text="").pack(side="left", padx=(0, 12))
            else:
                ctk.CTkLabel(row, text="🤖", font=ctk.CTkFont(size=24)).pack(side="left", padx=(0, 12))
            
            bubble = ctk.CTkFrame(
                row,
                fg_color=self.colors["bg_bubble_ai"],
                corner_radius=18
            )
            bubble.pack(side="left", fill="x", expand=True)
            
            ctk.CTkLabel(
                bubble,
                text=content,
                wraplength=700,
                justify="left",
                text_color=self.colors["text_primary"],
                font=ctk.CTkFont(size=14),
                padx=16,
                pady=12
            ).pack(fill="x")
        
        self.messages_frame._parent_canvas.yview_moveto(1.0)
    
    def set_status(self, text: str, color: str = "#10a37f"):
        self.status_label.configure(text=text, text_color=color)
    
    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = THEMES[theme]
        self.configure(fg_color=self.colors["bg_main"])
        self.header.configure(fg_color="transparent")
        self.welcome_frame.configure(fg_color="transparent")
        self.messages_frame.configure(fg_color=self.colors["bg_main"])
        self.model_label.configure(text_color=self.colors["text_secondary"])


# ==========================================
# ОБЛАСТЬ ВВОДА
# ==========================================
class InputArea(ctk.CTkFrame):
    def __init__(self, master, theme: str = "dark", assets: dict = None, on_send=None, **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)
        self.theme = theme
        self.colors = THEMES[theme]
        self.assets = assets or {}
        self.on_send = on_send
        
        self._build_ui()
    
    def _build_ui(self):
        input_frame = ctk.CTkFrame(
            self,
            fg_color=self.colors["bg_input"],
            corner_radius=12
        )
        input_frame.pack(fill="x", padx=20, pady=10)
        
        self.textbox = ctk.CTkTextbox(
            input_frame,
            height=55,
            font=ctk.CTkFont(size=14),
            wrap="word",
            fg_color=self.colors["bg_input"],
            border_width=0,
            text_color=self.colors["text_primary"]
        )
        self.textbox.pack(side="left", fill="both", expand=True, padx=15, pady=12)
        self.textbox.bind("<Return>", self._on_enter)
        self.textbox.bind("<Shift-Return>", lambda e: None)
        self.textbox.insert("1.0", "Message RAG Assistant...")
        self.textbox.bind("<FocusIn>", self._on_focus_in)
        self.textbox.bind("<FocusOut>", self._on_focus_out)
        
        send_icon = self.assets.get("send")
        send_btn = ctk.CTkButton(
            input_frame,
            text="",
            image=send_icon if send_icon else None,
            command=self._handle_send,
            width=40,
            height=40,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            font=ctk.CTkFont(size=20, weight="bold"),
            corner_radius=20
        )
        if not send_icon:
            send_btn.configure(text="↑", text_color="#ffffff")
        send_btn.pack(side="right", padx=(0, 10), pady=10)
        
        self.disclaimer_label = ctk.CTkLabel(
            self,
            text="Модель может ошибаться. Проверяйте важную информацию.",
            font=ctk.CTkFont(size=11),
            text_color=self.colors["text_secondary"]
        )
        self.disclaimer_label.pack(side="left", padx=20, pady=(0, 10))
    
    def _on_focus_in(self, event):
        if self.textbox.get("1.0", "end-1c").strip() == "Message RAG Assistant...":
            self.textbox.delete("1.0", "end")
    
    def _on_focus_out(self, event):
        if not self.textbox.get("1.0", "end-1c").strip():
            self.textbox.insert("1.0", "Message RAG Assistant...")
    
    def _on_enter(self, event):
        if not event.state & 1:
            self._handle_send()
            return "break"
    
    def _handle_send(self):
        text = self.textbox.get("1.0", "end-1c").strip()
        if not text or text == "Message RAG Assistant...":
            return
        self.textbox.delete("1.0", "end")
        if self.on_send:
            self.on_send(text)
    
    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = THEMES[theme]
        self.textbox.configure(
            fg_color=self.colors["bg_input"],
            text_color=self.colors["text_primary"]
        )
        self.disclaimer_label.configure(text_color=self.colors["text_secondary"])


# ==========================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# ==========================================
class AviationRAGApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self.geometry("1400x900")
        self.minsize(1100, 700)
        
        self.theme = "dark"
        self.colors = THEMES[self.theme]
        
        self.assets = self._load_assets()
        
        icon_path = find_image(ASSETS_DIR / "icon.png")
        if icon_path:
            try:
                self.iconbitmap(str(icon_path))
            except:
                pass
        
        self.chat_manager = ChatManager()
        self.rag_system = None
        self.is_processing = False
        
        self._build_ui()
        self._load_current_chat()
    
    def _load_assets(self):
        assets = {}
        
        logo = load_image_safe(ASSETS_DIR / "logo.png", (80, 80))
        if logo:
            assets["logo"] = logo
        
        for name in ["new_chat", "clear", "settings", "send"]:
            img = load_image_safe(ASSETS_DIR / "icons" / f"{name}.png", (20, 20))
            if img:
                assets[name] = img
        
        for name in ["user", "assistant"]:
            img = load_image_safe(ASSETS_DIR / "avatars" / f"{name}.png", (36, 36))
            if img:
                assets[name] = img
        
        bg = load_image_safe(ASSETS_DIR / "background.png", (1920, 1080))
        if bg:
            assets["background"] = bg
        
        return assets
    
    def _build_ui(self):
        self.configure(fg_color=self.colors["bg_main"])
        
        # Используем pack для надёжности
        self.sidebar = Sidebar(
            self,
            chat_manager=self.chat_manager,
            theme=self.theme,
            assets=self.assets,
            fg_color=self.colors["bg_sidebar"]
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.set_app_ref(self)
        
        # Правая часть
        self.right_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_main"], corner_radius=0)
        self.right_frame.pack(side="right", fill="both", expand=True)
        
        self.chat_area = ChatArea(self.right_frame, theme=self.theme, assets=self.assets, fg_color=self.colors["bg_main"])
        self.chat_area.pack(fill="both", expand=True)
        
        self.input_area = InputArea(
            self.right_frame,
            theme=self.theme,
            assets=self.assets,
            on_send=self._send_message,
            fg_color=self.colors["bg_main"]
        )
        self.input_area.pack(fill="x", side="bottom")
    
    def _new_chat(self):
        self.chat_manager.create_new_chat()
        self.sidebar.update_chat_list()
        self._load_current_chat()
    
    def _switch_chat(self, chat_id):
        self.chat_manager.switch_chat(chat_id)
        self.sidebar.update_chat_list()
        self._load_current_chat()
    
    def _rename_chat(self, chat_id):
        chat_name = self.chat_manager.chats[chat_id]["name"]
        
        def on_rename(new_name):
            self.chat_manager.rename_chat(chat_id, new_name)
            self.sidebar.update_chat_list()
        
        RenameDialog(
            self,
            "Переименовать чат",
            chat_name,
            on_rename,
            self.theme
        )
    
    def _delete_chat(self, chat_id):
        def on_confirm(result):
            if result:
                self.chat_manager.delete_chat(chat_id)
                self.sidebar.update_chat_list()
                self._load_current_chat()
        
        ConfirmDialog(
            self,
            "Удалить чат",
            "Вы уверены, что хотите удалить этот чат?",
            on_confirm,
            self.theme
        )
    
    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.colors = THEMES[self.theme]
        self.configure(fg_color=self.colors["bg_main"])
        self.right_frame.configure(fg_color=self.colors["bg_main"])
        self.sidebar.set_theme(self.theme)
        self.chat_area.set_theme(self.theme)
        self.input_area.set_theme(self.theme)
    
    def _show_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Настройки")
        win.geometry("450x380")
        win.resizable(False, False)
        win.configure(fg_color=self.colors["bg_sidebar"])
        win.transient(self)
        
        ctk.CTkLabel(
            win,
            text="Настройки системы",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack(pady=30)
        
        info = (
            "Модель: Gemma2 9B (Ollama)\n"
            "База: PRL-27СМ Documentation\n"
            "Поиск: Hybrid (BM25 + Vector + RRF)\n"
            "Реранкер: BAAI/bge-reranker-v2-m3\n"
            "Parent-Child Retrieval: Enabled\n"
            "Self-RAG: Enabled\n"
            "Query Rewriting: Enabled\n\n"
            f"Версия: {APP_VERSION}"
        )
        
        ctk.CTkLabel(
            win,
            text=info,
            font=ctk.CTkFont(size=13),
            text_color=self.colors["text_primary"],
            justify="left"
        ).pack(pady=20)
    
    def _load_current_chat(self):
        chat = self.chat_manager.get_current_chat()
        if chat:
            self.chat_area.clear_messages()
            if chat["messages"]:
                self.chat_area.show_messages()
                for msg in chat["messages"]:
                    self.chat_area.add_message(msg["role"], msg["content"])
            else:
                self.chat_area.show_welcome()
    
    def _send_message(self, user_input: str):
        if self.is_processing:
            return
        
        self.chat_area.show_messages()
        self.chat_area.add_message("user", user_input)
        self.chat_manager.add_message("user", user_input)
        
        chat = self.chat_manager.get_current_chat()
        if chat and chat["name"] == "Новый чат" and len(chat["messages"]) == 1:
            new_name = user_input[:40] + ("..." if len(user_input) > 40 else "")
            self.chat_manager.rename_chat(self.chat_manager.current_chat_id, new_name)
            self.sidebar.update_chat_list()
        
        self.is_processing = True
        self.chat_area.set_status("● Думаю...", "#f59e0b")
        
        threading.Thread(target=self._process, args=(user_input,), daemon=True).start()
    
    def _process(self, user_input: str):
        try:
            if self.rag_system is None:
                self.chat_area.set_status("● Загрузка модели...", "#f59e0b")
                self.rag_system = SmartRAG()
            
            self.chat_area.set_status("● Поиск в базе...", "#f59e0b")
            response = self.rag_system.query(user_input)
            clean = response.replace("[С поиском]:\n", "").replace("[Без поиска]: ", "")
            
            self.after(0, self.chat_area.add_message, "assistant", clean)
            self.chat_manager.add_message("assistant", clean)
            self.chat_area.set_status("● Готов", "#10a37f")
            self.is_processing = False
            
        except Exception as e:
            err = f"Ошибка: {str(e)}"
            self.after(0, self.chat_area.add_message, "assistant", err)
            self.chat_area.set_status("● Ошибка", "#dc2626")
            self.is_processing = False


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = AviationRAGApp()
    app.mainloop()