import customtkinter as ctk
from tkinter import messagebox
import json
import threading
from pathlib import Path
import sys
from PIL import Image
import tkinter as tk  
import subprocess
import platform
sys.path.append(str(Path(__file__).parent))
from smart_rag import SmartRAG
import subprocess
import platform
import re
import tkinter as tk
from tkinter import ttk 
import textwrap

_TABLE_STYLE_COUNTER = 0

def _make_selectable_text(parent, colors, wrap="word", bg=None, fg=None,
                          font=("SF Pro Display", 14), padx=10, pady=4):
    """Read-only текстовый блок: можно выделять мышью и копировать, но нельзя редактировать."""
    bg = bg or colors["bg_bubble_ai"]
    fg = fg or colors["text_primary"]
    text = tk.Text(
        parent, wrap=wrap, bg=bg, fg=fg, font=font,
        borderwidth=0, highlightthickness=0, relief="flat",
        padx=padx, pady=pady, cursor="arrow",
        selectbackground=colors["accent"],
        selectforeground="#ffffff",
        inactiveselectbackground=colors["border"],
        insertbackground=bg,
    )
    
    attach_visible_selection(text, colors)
    text.tag_configure("sel", background=colors["accent"], foreground="#ffffff")
    
    last = {"n": -1, "w": -1}
    def _autoheight(e=None):
        w = text.winfo_width()
        if w < 10:
            return
        if w == last["w"] and last["n"] > 0:
            return
        text.update_idletasks()
        try:
            n = text.count("1.0", "end-1c", "displaylines")[0]
        except Exception:
            n = int(str(text.index("end-1c")).split(".")[0])
        n = max(1, n)
        last["w"] = w
        if n != last["n"]:
            last["n"] = n
            text.configure(height=n)
    text.bind("<Configure>", _autoheight)
    
    def _wheel(e):
        w = parent
        while w is not None and not hasattr(w, "_parent_canvas"):
            w = getattr(w, "master", None)
        if w is not None:
            c = w._parent_canvas
            d = getattr(e, "delta", 0)
            if e.num == 5 or d < 0:
                c.yview_scroll(2, "units")
            elif e.num == 4 or d > 0:
                c.yview_scroll(-2, "units")
            c.xview_moveto(0)
        return "break"
    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        text.bind(seq, _wheel)
    
    def _refresh_hl():
        try:
            a, b = text.tag_ranges("sel")
            text.tag_remove("hl", "1.0", "end")
            if a and b:
                text.tag_add("hl", a, b)
        except Exception:
            pass
    
    def _copy_sel(e=None):
        try:
            sel = text.get("sel.first", "sel.last")
            if sel:
                set_clipboard_text(sel)
                try:
                    text.clipboard_clear()
                    text.clipboard_append(sel)
                except Exception:
                    pass
                print(f"Скопировано выделение: {sel[:40]}...")
                text.tag_remove("sel", "1.0", "end")
                text.tag_remove("hl", "1.0", "end")
        except tk.TclError:
            pass
        return "break"
    
    def _select_all(e=None):
        text.tag_add("sel", "1.0", "end")
        _refresh_hl()
        return "break"
    
    # 🚀 ВОССТАНОВЛЕННЫЕ привязки копирования
    text.bind("<Command-c>", _copy_sel)
    text.bind("<Control-c>", _copy_sel)
    text.bind("<<Copy>>", _copy_sel)
    text.bind("<Command-a>", _select_all)
    text.bind("<Control-a>", _select_all)
    
    # Блокируем редактирование (read-only), кроме навигации и копирования
    ALLOWED = {"Left", "Right", "Up", "Down", "Home", "End",
               "Prior", "Next", "Page_Up", "Page_Down"}
    def _block(e):
        if e.keysym in ALLOWED:
            return None
        is_cmd = bool(e.state & 0x40) or bool(e.state & 0x04)
        if is_cmd and e.keysym.lower() in ("c", "a"):
            return None
        return "break"
    text.bind("<Key>", _block)
    
    def _menu(e):
        m = tk.Menu(text, tearoff=0, bg=colors["bg_input"], fg=colors["text_primary"],
                    activebackground=colors["border"], activeforeground=colors["text_primary"])
        m.add_command(label="Копировать выделение", command=_copy_sel)
        m.add_command(label="Копировать блок целиком",
                      command=lambda: (set_clipboard_text(text.get("1.0", "end-1c")),
                                       text.tag_remove("sel", "1.0", "end"),
                                       text.tag_remove("hl", "1.0", "end")))
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
        return "break"
    text.bind("<Button-3>", _menu)
    return text

def _avail_width(widget, default=950):
    """Реальная доступная ширина: поднимаемся вверх по родителям до видимого размера."""
    w = widget
    for _ in range(8):
        try:
            ww = w.winfo_width()
            if ww and ww > 100:
                return max(500, min(default, ww - 70))
        except Exception:
            pass
        w = getattr(w, "master", None)
    return default

def parse_markdown_to_widgets(parent, text: str, colors: dict):
    """
    Парсит Markdown и создаёт виджеты внутри parent.
    Текстовые блоки — выделяемые tk.Text; таблицы — ttk.Treeview.
    """
    lines = text.split('\n')
    i = 0
    indent_next = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # ========== БЛОКИ КОДА (``` ... ```) ==========
        if line.startswith('```'):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code_text = '\n'.join(code_lines)
            
            code_frame = ctk.CTkFrame(
                parent, fg_color="#0d1117", corner_radius=10,
                border_width=1, border_color=colors["border"]
            )
            code_frame.pack(fill="x", pady=10, padx=10)
            
            header_row = ctk.CTkFrame(code_frame, fg_color="transparent")
            header_row.pack(fill="x", padx=14, pady=(10, 0))
            ctk.CTkLabel(
                header_row, text=lang if lang else "code",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=colors["accent"], anchor="w"
            ).pack(side="left")
            
            code_widget = _make_selectable_text(
                code_frame, colors, wrap="none",
                bg="#0d1117", fg="#e6edf3",
                font=("Courier New", 13), padx=14, pady=10
            )
            code_widget.insert("end", code_text)
            code_widget.pack(fill="x", padx=2, pady=(4, 10))
            continue
        
        # Сброс отступа вложенности
        if not (line.startswith('- ') or line.startswith('* ')):
            indent_next = 0
        
        # ========== ЗАГОЛОВКИ ЛЮБОГО УРОВНЯ ==========
        heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if heading_match:
            level = len(heading_match.group(1))
            sizes = {1: 20, 2: 18, 3: 16, 4: 15, 5: 14, 6: 14}
            h = _make_selectable_text(
                parent, colors,
                font=("SF Pro Display", sizes.get(level, 14), "bold"),
                padx=10, pady=2
            )
            h.insert("end", heading_match.group(2))
            h.pack(fill="x", pady=(15, 5))
            i += 1
            continue
        
        # ========== ТАБЛИЦЫ ==========
        if line.startswith('|') and '|' in line:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            
            has_separator = any('---' in l for l in table_lines)
            
            if has_separator and len(table_lines) >= 3:
                def split_row(row):
                    parts = row.split('|')
                    if parts and parts[0].strip() == '':
                        parts = parts[1:]
                    if parts and parts[-1].strip() == '':
                        parts = parts[:-1]
                    return [p.strip() for p in parts]
                
                headers = split_row(table_lines[0])
                separator_idx = next((idx for idx, l in enumerate(table_lines) if '---' in l), 1)
                raw_data = table_lines[separator_idx + 1:]
                num_cols = len(headers)
                
                valid_rows = []
                for data_line in raw_data:
                    cells = split_row(data_line)
                    if not any(cells):
                        continue
                    while len(cells) < num_cols:
                        cells.append("")
                    valid_rows.append(cells[:num_cols])
                
                AVAILABLE_WIDTH = _avail_width(parent)
                HEADER_CHAR_PX = 8
                base_widths = [max(120, len(h) * HEADER_CHAR_PX + 24) for h in headers]
                total_base = sum(base_widths)
                
                if total_base > AVAILABLE_WIDTH:
                    scale = AVAILABLE_WIDTH / total_base
                    col_widths = [int(w * scale) for w in base_widths]
                else:
                    data_weights = []
                    for col_idx in range(num_cols):
                        mw = 0
                        for cells in valid_rows:
                            mw = max(mw, len(cells[col_idx]))
                        data_weights.append(mw)
                    tw = sum(data_weights) or 1
                    extra = AVAILABLE_WIDTH - total_base
                    col_widths = [
                        base_widths[c] + int(extra * data_weights[c] / tw)
                        for c in range(num_cols)
                    ]
                
                CHAR_PX = 7
                LINE_PX = 18
                wrapped_rows = []
                max_lines = 1
                for cells in valid_rows:
                    wrapped = []
                    for col_idx, cell in enumerate(cells):
                        chars_per_line = max(10, int((col_widths[col_idx] - 24) / CHAR_PX))
                        wtext = textwrap.fill(cell, width=chars_per_line) if cell else ""
                        max_lines = max(max_lines, wtext.count("\n") + 1 if wtext else 1)
                        wrapped.append(wtext)
                    wrapped_rows.append(wrapped)
                rowheight = max_lines * LINE_PX + 12
                
                table_container = ctk.CTkFrame(
                    parent, fg_color=colors["bg_input"], corner_radius=10,
                    border_width=2, border_color=colors["border"]
                )
                table_container.pack(fill="x", pady=12, padx=10)
                
                # Правый клик по таблице — копирует её как TSV (вставится в Excel/Docs таблицей)
                def _copy_table(e, hdrs=headers, rows=valid_rows):
                    tsv = "\t".join(hdrs) + "\n" + "\n".join("\t".join(r) for r in rows)
                    set_clipboard_text(tsv)
                    print("Таблица скопирована в буфер (TSV)")
                    return "break"
                table_container.bind("<Button-3>", _copy_table)
                
                tree = ttk.Treeview(
                    table_container, columns=headers, show="headings",
                    height=min(len(wrapped_rows), 15), selectmode="none"
                )
                for col_idx, header in enumerate(headers):
                    tree.heading(f"#{col_idx+1}", text=header, anchor="w")
                    tree.column(f"#{col_idx+1}", width=col_widths[col_idx], minwidth=80, anchor="w", stretch=True)
                for row_idx, cells in enumerate(wrapped_rows):
                    tag = "odd" if row_idx % 2 else "even"
                    tree.insert("", "end", values=cells, tags=(tag,))
                
                style = ttk.Style()
                try:
                    if style.theme_use() != "clam":
                        style.theme_use("clam")
                except Exception:
                    pass
                
                global _TABLE_STYLE_COUNTER
                _TABLE_STYLE_COUNTER += 1
                style_name = f"Tbl{_TABLE_STYLE_COUNTER}.Treeview"
                
                style.configure(
                    style_name, background=colors["bg_input"], foreground=colors["text_primary"],
                    fieldbackground=colors["bg_input"], rowheight=rowheight,
                    font=("SF Pro Display", 12), borderwidth=0,
                )
                style.configure(
                    f"{style_name}.Heading", background=colors["accent"], foreground="#ffffff",
                    font=("SF Pro Display", 13, "bold"), relief="flat", borderwidth=0,
                )
                style.map(style_name, background=[("selected", colors["border"])],
                          foreground=[("selected", "#ffffff")])
                
                tree.tag_configure("odd", background=colors["bg_input"])
                tree.tag_configure("even", background=colors["bg_main"])
                tree.configure(style=style_name)
                
                if len(wrapped_rows) > 15:
                    scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=tree.yview)
                    tree.configure(yscrollcommand=scrollbar.set)
                    tree.pack(side="left", fill="both", expand=True)
                    scrollbar.pack(side="right", fill="y")
                else:
                    tree.pack(fill="x", expand=True, padx=5, pady=5)
                continue
            else:
                clean_line = line.replace('**', '').replace('|', '')
                t = _make_selectable_text(parent, colors, padx=10, pady=3)
                t.insert("end", clean_line)
                t.pack(fill="x")
                i += 1
                continue
        
        # ========== СПИСКИ ==========
        if line.startswith('- ') or line.startswith('* '):
            item_text = line[2:].replace('**', '').strip()
            is_intro = item_text.endswith(':')
            
            if is_intro:
                t = _make_selectable_text(
                    parent, colors, font=("SF Pro Display", 14, "bold"), padx=10, pady=2
                )
                t.insert("end", item_text)
                t.pack(fill="x", pady=2)
                indent_next = 30
            else:
                t = _make_selectable_text(parent, colors, padx=0, pady=2)
                m1, m2 = 10 + indent_next, 26 + indent_next
                t.tag_configure("bullet", foreground=colors["accent"],
                                font=("SF Pro Display", 15, "bold"),
                                lmargin1=m1, lmargin2=m2)
                t.tag_configure("body", lmargin1=m1, lmargin2=m2)
                t.insert("end", "•  ", "bullet")
                t.insert("end", item_text, "body")
                t.pack(fill="x", pady=2)
            i += 1
            continue
        
        numbered_match = re.match(r'^(\d+)\.\s+(.*)', line)
        if numbered_match:
            num = numbered_match.group(1)
            item_text = numbered_match.group(2).replace('**', '')
            t = _make_selectable_text(parent, colors, padx=0, pady=2)
            t.tag_configure("num", foreground=colors["accent"],
                            font=("SF Pro Display", 14, "bold"),
                            lmargin1=10, lmargin2=40)
            t.tag_configure("body", lmargin1=10, lmargin2=40)
            t.insert("end", f"{num}.  ", "num")
            t.insert("end", item_text, "body")
            t.pack(fill="x", pady=2)
            i += 1
            continue
        
        # ========== ПУСТЫЕ СТРОКИ ==========
        if not line:
            i += 1
            continue
        
        # ========== ОБЫЧНЫЙ ТЕКСТ ==========
        clean_line = line.replace('**', '')
        t = _make_selectable_text(parent, colors, padx=10, pady=3)
        t.insert("end", clean_line)
        t.pack(fill="x")
        i += 1

def build_table_widget(master, table_lines, colors, available=None):
    """Собирает Treeview-таблицу; available — макс. ширина в px."""
    def split_row(row):
        parts = row.split('|')
        if parts and parts[0].strip() == '':
            parts = parts[1:]
        if parts and parts[-1].strip() == '':
            parts = parts[:-1]
        return [p.strip() for p in parts]
    
    headers = split_row(table_lines[0])
    separator_idx = next((idx for idx, l in enumerate(table_lines) if '---' in l), 1)
    raw_data = table_lines[separator_idx + 1:]
    num_cols = len(headers)
    
    valid_rows = []
    for data_line in raw_data:
        cells = split_row(data_line)
        if not any(cells):
            continue
        while len(cells) < num_cols:
            cells.append("")
        valid_rows.append(cells[:num_cols])
    
    AVAILABLE_WIDTH = available or _avail_width(master)
    HEADER_CHAR_PX = 8
    base_widths = [max(120, len(h) * HEADER_CHAR_PX + 24) for h in headers]
    total_base = sum(base_widths)
    if total_base > AVAILABLE_WIDTH:
        scale = AVAILABLE_WIDTH / total_base
        col_widths = [int(w * scale) for w in base_widths]
    else:
        data_weights = []
        for col_idx in range(num_cols):
            mw = 0
            for cells in valid_rows:
                mw = max(mw, len(cells[col_idx]))
            data_weights.append(mw)
        tw = sum(data_weights) or 1
        extra = AVAILABLE_WIDTH - total_base
        col_widths = [base_widths[c] + int(extra * data_weights[c] / tw) for c in range(num_cols)]
    
    CHAR_PX, LINE_PX = 7, 18
    wrapped_rows, max_lines = [], 1
    for cells in valid_rows:
        wrapped = []
        for col_idx, cell in enumerate(cells):
            cpl = max(10, int((col_widths[col_idx] - 24) / CHAR_PX))
            wtext = textwrap.fill(cell, width=cpl) if cell else ""
            max_lines = max(max_lines, wtext.count("\n") + 1 if wtext else 1)
            wrapped.append(wtext)
        wrapped_rows.append(wrapped)
    rowheight = max_lines * LINE_PX + 12
    
    container = ctk.CTkFrame(master, fg_color=colors["bg_input"], corner_radius=10,
                             border_width=2, border_color=colors["border"])
    
    tree = ttk.Treeview(container, columns=headers, show="headings",
                        height=min(len(wrapped_rows), 15), selectmode="none")
    for col_idx, header in enumerate(headers):
        tree.heading(f"#{col_idx+1}", text=header, anchor="w")
        tree.column(f"#{col_idx+1}", width=col_widths[col_idx], minwidth=60,
                    anchor="w", stretch=False)   # ← stretch=False: сумма ширин фиксирована
    for row_idx, cells in enumerate(wrapped_rows):
        tree.insert("", "end", values=cells, tags=("odd" if row_idx % 2 else "even",))
    
    style = ttk.Style()
    try:
        if style.theme_use() != "clam":
            style.theme_use("clam")
    except Exception:
        pass
    global _TABLE_STYLE_COUNTER
    _TABLE_STYLE_COUNTER += 1
    style_name = f"Tbl{_TABLE_STYLE_COUNTER}.Treeview"
    style.configure(style_name, background=colors["bg_input"], foreground=colors["text_primary"],
                    fieldbackground=colors["bg_input"], rowheight=rowheight,
                    font=("SF Pro Display", 12), borderwidth=0)
    style.configure(f"{style_name}.Heading", background=colors["accent"], foreground="#ffffff",
                    font=("SF Pro Display", 13, "bold"), relief="flat", borderwidth=0)
    tree.tag_configure("odd", background=colors["bg_input"])
    tree.tag_configure("even", background=colors["bg_main"])
    tree.configure(style=style_name)
    tree.pack(fill="x", padx=5, pady=5)
    return container


def render_markdown_to_text(textw, text, colors, wheel_handler=None, table_max=900):
    """Рендерит markdown в tk.Text с тегами — текст МОЖНО выделять курсором"""
    textw.tag_configure("h1", font=("SF Pro Display", 20, "bold"), spacing1=14, spacing3=8)
    textw.tag_configure("h2", font=("SF Pro Display", 18, "bold"), spacing1=12, spacing3=6)
    textw.tag_configure("h3", font=("SF Pro Display", 16, "bold"), spacing1=10, spacing3=5)
    textw.tag_configure("h4", font=("SF Pro Display", 15, "bold"), spacing1=8, spacing3=4)
    textw.tag_configure("plain", font=("SF Pro Display", 14), spacing1=2, spacing3=8, justify="left")
    # Нумерация: БЕЗ отступа, переносы выравниваются после цифры
    textw.tag_configure("num_mark", font=("SF Pro Display", 14, "bold"),
                        foreground=colors["accent"], lmargin1=0, lmargin2=0)
    textw.tag_configure("num_body", font=("SF Pro Display", 14), spacing1=2, spacing3=5,
                        lmargin1=0, lmargin2=30, justify="left")
    # Пункты 1-го уровня: отступ 36px целиком (маркер + текст)
    textw.tag_configure("bul_mark", font=("SF Pro Display", 15, "bold"),
                        foreground=colors["accent"], lmargin1=36, lmargin2=36)
    textw.tag_configure("bul_body", font=("SF Pro Display", 14), spacing1=2, spacing3=5,
                        lmargin1=36, lmargin2=56, justify="left")
    # Вложенные пункты (под вводными строками): отступ 64px
    textw.tag_configure("bul2_mark", font=("SF Pro Display", 15, "bold"),
                        foreground=colors["accent"], lmargin1=64, lmargin2=64)
    textw.tag_configure("bul2_body", font=("SF Pro Display", 14), spacing1=2, spacing3=5,
                        lmargin1=64, lmargin2=84, justify="left")
    textw.tag_configure("mark", font=("SF Pro Display", 14, "bold"), foreground=colors["accent"])
    textw.tag_configure("code_lang", font=("SF Pro Display", 11, "bold"),
                        foreground=colors["accent"], spacing1=8, spacing3=2)
    textw.tag_configure("code", font=("Courier New", 13), background="#0d1117",
                        foreground="#e6edf3", lmargin1=16, lmargin2=16, spacing3=8)
    
    embedded = []   # список встроенных виджетов (таблиц) для расчёта высоты
    lines = text.split('\n')
    i, indent = 0, 0
    while i < len(lines):
        s = lines[i].strip()
        
        if not (s.startswith('- ') or s.startswith('* ')):
            indent = 0
        
        # Блок кода
        if s.startswith('```'):
            lang = s[3:].strip()
            buf = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            if lang:
                textw.insert("end", lang + "\n", "code_lang")
            textw.insert("end", "\n".join(buf) + "\n", "code")
            continue
        
        # Заголовки
        m = re.match(r'^(#{1,6})\s+(.*)', s)
        if m:
            tag = {1: "h1", 2: "h2", 3: "h3"}.get(len(m.group(1)), "h4")
            textw.insert("end", m.group(2) + "\n", tag)
            i += 1
            continue
        
        # Таблица -> встраиваем виджет прямо в текст
        if s.startswith('|'):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                tbl.append(lines[i].strip())
                i += 1
            if any('---' in l for l in tbl) and len(tbl) >= 3:
                widget = build_table_widget(textw, tbl, colors, available=table_max)
                textw.window_create("end", window=widget, padx=10, pady=8)
                embedded.append(widget)
                textw.insert("end", "\n")
            continue
        
        # Списки
        if s.startswith('- ') or s.startswith('* '):
            item = s[2:].replace('**', '').strip()
            if item.endswith(':'):
                textw.insert("end", item + "\n", "h4")
                indent = 1
            else:
                if indent:
                    textw.insert("end", "• ", "bul2_mark")
                    textw.insert("end", item + "\n", "bul2_body")
                else:
                    textw.insert("end", "• ", "bul_mark")
                    textw.insert("end", item + "\n", "bul_body")
            i += 1
            continue
        
        # Нумерованные пункты — у левого края
        m2 = re.match(r'^(\d+)\.\s+(.*)', s)
        if m2:
            textw.insert("end", f"{m2.group(1)}. ", "num_mark")
            textw.insert("end", m2.group(2).replace('**', '') + "\n", "num_body")
            i += 1
            continue
        
        if not s:
            i += 1
            continue
        
        textw.insert("end", s.replace('**', '') + "\n", "plain")
        i += 1
    
    
    
    # Прокрутка колесом над ответом уходит внешнему скроллу чата
    if wheel_handler:
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            textw.bind(seq, wheel_handler)
    return embedded

def render_markdown_table(table_text: str, colors: dict) -> ctk.CTkFrame:
    """Преобразует Markdown-таблицу в CTk-виджет"""
    lines = table_text.strip().split('\n')
    if len(lines) < 2:
        return None
    
    # Парсим заголовки
    headers = [cell.strip() for cell in lines[0].split('|') if cell.strip()]
    
    # Создаем фрейм для таблицы
    table_frame = ctk.CTkFrame(None, fg_color=colors["bg_input"], corner_radius=8)
    
    # Заголовки
    header_frame = ctk.CTkFrame(table_frame, fg_color=colors["border"], corner_radius=0)
    header_frame.pack(fill="x")
    for header in headers:
        ctk.CTkLabel(
            header_frame, text=header,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=colors["text_primary"],
            padx=10, pady=8
        ).pack(side="left", expand=True, fill="x")
    
    # Данные
    for line in lines[2:]:  # Пропускаем разделитель
        cells = [cell.strip() for cell in line.split('|') if cell.strip()]
        if cells:
            row_frame = ctk.CTkFrame(table_frame, fg_color="transparent")
            row_frame.pack(fill="x")
            for cell in cells:
                ctk.CTkLabel(
                    row_frame, text=cell,
                    font=ctk.CTkFont(size=12),
                    text_color=colors["text_primary"],
                    padx=10, pady=6
                ).pack(side="left", expand=True, fill="x")
    
    return table_frame

def get_clipboard_text():
    """Получить текст из буфера обмена (работает на всех платформах)"""
    try:
        if platform.system() == 'Darwin':  # macOS
            result = subprocess.run(['pbpaste'], capture_output=True, text=True)
            return result.stdout
        elif platform.system() == 'Linux':
            result = subprocess.run(['xclip', '-selection', 'clipboard', '-o'], 
                                  capture_output=True, text=True)
            return result.stdout
        else:  # Windows
            result = subprocess.run(['clip'], capture_output=True, text=True)
            return result.stdout
    except Exception as e:
        print(f"Ошибка чтения буфера: {e}")
        return ""

def set_clipboard_text(text: str):
    """Установить текст в буфер обмена"""
    try:
        if platform.system() == 'Darwin':  # macOS
            proc = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
        elif platform.system() == 'Linux':
            proc = subprocess.Popen(['xclip', '-selection', 'clipboard'], 
                                  stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
        else:  # Windows
            proc = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
            proc.communicate(text.encode('utf-8'))
    except Exception as e:
        print(f"Ошибка записи в буфер: {e}")

def attach_visible_selection(text, colors):
    """Видимое выделение + корректное снятие подсветки."""
    text.tag_configure("hl", background=colors["accent"], foreground="#ffffff")
    
    def _refresh(e=None):
        try:
            a, b = text.tag_ranges("sel")
            text.tag_remove("hl", "1.0", "end")
            if a and b:
                text.tag_add("hl", a, b)
        except Exception:
            pass
        return None
    
    def _clear(e=None):
        # Безусловно гасим подсветку НАЖАТИЕМ мыши (до того, как Tk сбросит sel)
        text.tag_remove("hl", "1.0", "end")
        return None
    
    for seq in ("<B1-Motion>", "<ButtonRelease-1>", "<KeyRelease>"):
        text.bind(seq, _refresh)
    text.bind("<Button-1>", _clear, add="+")
    text.bind("<Escape>", lambda e: (text.tag_remove("sel", "1.0", "end"),
                                     text.tag_remove("hl", "1.0", "end")))
    return _refresh

def _fit_text_height(textw):
    """Точно подгоняет высоту tk.Text под контент (учитывает встроенные таблицы)."""
    try:
        textw.update_idletasks()
        import tkinter.font as tkfont
        ls = tkfont.Font(font=textw.cget("font")).metrics("linespace") or 20
        old_h = int(str(textw.cget("height")))
        # Временно раскрываем виджет, чтобы ВСЕ строки и таблицы отрисовались
        textw.configure(height=1500)
        textw.update_idletasks()
        d = textw.dlineinfo("end-1c")   # геометрия последней строки
        if d:
            pixel_h = d[1] + d[3] + 16  # y + высота строки + нижний паддинг
            need = max(1, -(-pixel_h // ls))  # округление вверх
        else:
            need = old_h
        textw.configure(height=need)
        textw.update_idletasks()
    except Exception:
        pass

# ==========================================
# ЦВЕТОВАЯ ПАЛИТРА "AVIATION COCKPIT"
# ==========================================
THEMES = {
    "dark": {
        "bg_main": "#1a1f2e",
        "bg_sidebar": "#0f1419",
        "bg_input": "#252b3b",
        "bg_bubble_user": "#2563eb",
        "bg_bubble_ai": "#252b3b",
        "text_primary": "#e2e8f0",
        "text_secondary": "#64748b",
        "accent": "#f59e0b",
        "accent_hover": "#d97706",
        "border": "#334155",
        "btn_text": "#e2e8f0",
        "status_ready": "#10b981",
        "status_busy": "#f59e0b",
        "status_error": "#ef4444",
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
    actual_path = find_image(image_path)
    if actual_path:
        try:
            img = Image.open(actual_path).convert("RGBA")
            img = img.resize(size, Image.LANCZOS)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception as e:
            print(f"Ошибка загрузки {actual_path}: {e}")
    return None


def load_background_image(image_path: Path, size: tuple) -> ctk.CTkImage | None:
    actual_path = find_image(image_path)
    if actual_path:
        try:
            img = Image.open(actual_path).convert("RGB")
            img = img.resize(size, Image.LANCZOS)
            return ctk.CTkImage(light_image=img, dark_image=img, size=size)
        except Exception as e:
            print(f"Ошибка загрузки фона {actual_path}: {e}")
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
# ДИАЛОГ ПЕРЕИМЕНОВАНИЯ
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
        super().__init__(master, width=280, corner_radius=0, **kwargs)
        self.chat_manager = chat_manager
        self.theme = theme
        self.colors = THEMES[theme]
        self.assets = assets or {}
        self.app_ref = None
        
        self.grid_propagate(False)
        self.grid_rowconfigure(3, weight=1)
        
        self._build_ui()
        self.update_chat_list()
    
    def set_app_ref(self, app):
        self.app_ref = app
    
    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent", height=120)
        header.grid(row=0, column=0, padx=12, pady=15, sticky="ew")
        header.grid_propagate(False)
        
        if "logo" in self.assets:
            ctk.CTkLabel(header, image=self.assets["logo"], text="").pack(pady=(0, 8))
        
        ctk.CTkLabel(
            header,
            text="Aviation RAG",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack()
        
        ctk.CTkLabel(
            header,
            text="AI Engine v1.0",
            font=ctk.CTkFont(size=11),
            text_color=self.colors["text_secondary"]
        ).pack()
        
        new_chat_icon = self.assets.get("new_chat")
        self.new_chat_btn = ctk.CTkButton(
            self,
            text="  Новый чат",
            image=new_chat_icon,
            command=self._handle_new_chat,
            height=45,
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"],
            text_color="#ffffff",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            corner_radius=10,
            compound="left"
        )
        self.new_chat_btn.grid(row=1, column=0, padx=12, pady=8, sticky="ew")
        
        ctk.CTkFrame(self, height=1, fg_color=self.colors["border"]).grid(
            row=2, column=0, padx=12, pady=10, sticky="ew"
        )
        
        self.chat_list_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=self.colors["border"],
            scrollbar_button_hover_color="#555555"
        )
        self.chat_list_frame.grid(row=3, column=0, padx=8, pady=4, sticky="nsew")
        
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=4, column=0, padx=12, pady=12, sticky="ew")
        
        clear_icon = self.assets.get("clear")
        self.delete_btn = ctk.CTkButton(
            bottom,
            text="  Удалить чат",
            image=clear_icon,
            command=self._handle_delete_current,
            height=40,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=13),
            anchor="w",
            corner_radius=8,
            compound="left"
        )
        self.delete_btn.pack(fill="x", pady=3)
        
        settings_icon = self.assets.get("settings")
        self.settings_btn = ctk.CTkButton(
            bottom,
            text="  Настройки",
            image=settings_icon,
            command=self._handle_settings,
            height=40,
            fg_color="transparent",
            hover_color=self.colors["bg_input"],
            text_color=self.colors["btn_text"],
            font=ctk.CTkFont(size=13),
            anchor="w",
            corner_radius=8,
            compound="left"
        )
        self.settings_btn.pack(fill="x", pady=3)
    
    def _handle_new_chat(self):
        if self.app_ref:
            self.app_ref._new_chat()
    
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
                text=f"  {chat_data['name'][:28]}{'...' if len(chat_data['name']) > 28 else ''}",
                command=lambda cid=chat_id: self._handle_switch(cid),
                height=42,
                anchor="w",
                fg_color=self.colors["accent"] if is_current else "transparent",
                hover_color=self.colors["bg_input"],
                text_color="#ffffff" if is_current else self.colors["btn_text"],
                font=ctk.CTkFont(size=13),
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
            fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"]
        )
        self.theme_btn.configure(
            text="  Тёмная тема" if theme == "dark" else "  Светлая тема",
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
# ОБЛАСТЬ ЧАТА С ФОНОМ
# ==========================================
class ChatArea(ctk.CTkFrame):
    def __init__(self, master, theme: str = "dark", assets: dict = None, on_send_example=None, **kwargs):
        super().__init__(master, corner_radius=0, **kwargs)
        self.theme = theme
        self.colors = THEMES[theme]
        self.assets = assets or {}
        self.on_send_example = on_send_example
        
        self._build_header()
        self._build_background()
        self._build_welcome()
        self._build_messages()
        
        self.welcome_frame.pack(fill="both", expand=True)
    
    def _build_header(self):
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=50)
        self.header.pack(fill="x", padx=20, pady=10)
        self.header.pack_propagate(False)
        
        self.model_label = ctk.CTkLabel(
            self.header,
            text="Gemma2 9B  •  PRL-27СМ RAG",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=self.colors["text_secondary"]
        )
        self.model_label.pack(side="left")
        
        self.status_label = ctk.CTkLabel(
            self.header,
            text="● Готов",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=self.colors["status_ready"]
        )
        self.status_label.pack(side="right")
    
    def _build_background(self):
        if "background" in self.assets:
            self.bg_label = ctk.CTkLabel(
                self,
                image=self.assets["background"],
                text=""
            )
        else:
            self.bg_label = None
    
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
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color=self.colors["text_primary"]
        ).pack(pady=(0, 10))
        
        ctk.CTkLabel(
            content,
            text="Задайте вопрос по документации ПРЛ-27СМ",
            font=ctk.CTkFont(size=15),
            text_color=self.colors["text_secondary"]
        ).pack(pady=(0, 50))
        
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
                height=55,
                width=300,
                fg_color=self.colors["bg_input"],
                hover_color=self.colors["border"],
                border_width=1,
                border_color=self.colors["border"],
                text_color=self.colors["text_primary"],
                font=ctk.CTkFont(size=14),
                corner_radius=12,
                anchor="w",
                command=lambda t=text: self._send_example(t)
            )
            btn.grid(row=i//2, column=i%2, padx=10, pady=8, sticky="ew")
    
    def _send_example(self, text: str):
        if self.on_send_example:
            self.on_send_example(text)
    
    def _build_messages(self):
        self.messages_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=self.colors["border"],
            scrollbar_button_hover_color="#555555"
        )
        # Безопасная привязка прокрутки только к этому фрейму
        self.messages_frame.bind("<MouseWheel>", self._on_mousewheel)
        self.messages_frame.bind("<Button-4>", self._on_mousewheel)
        self.messages_frame.bind("<Button-5>", self._on_mousewheel)
        
    
    def _on_mousewheel(self, event):
        c = self.messages_frame._parent_canvas
        d = getattr(event, "delta", 0)
        if event.num == 4 or d > 0:
            step = -2
        elif event.num == 5 or d < 0:
            step = 2
        else:
            return "break"
        c.yview_scroll(step, "units")
        c.xview_moveto(0)   # контент никогда не уезжает влево/вправо
        return "break"
    
    def show_welcome(self):
        if self.messages_frame.winfo_manager():
            self.messages_frame.pack_forget()
        if self.bg_label:
            self.bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.bg_label.lower()
        self.welcome_frame.pack(fill="both", expand=True)
        self.welcome_frame.lift()
    
    def show_messages(self):
        if self.welcome_frame.winfo_manager():
            self.welcome_frame.pack_forget()
        if self.bg_label:
            self.bg_label.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.bg_label.lower()
        self.messages_frame.pack(fill="both", expand=True)
        self.messages_frame.lift()
    
    def clear_messages(self):
        for widget in self.messages_frame.winfo_children():
            widget.destroy()
    
    def add_message(self, role: str, content: str):
        outer = ctk.CTkFrame(self.messages_frame, fg_color="transparent")
        outer.pack(fill="x", pady=10)
        
        # Строка ВСЕГДА на всю ширину (side="top"), выравнивание — внутри
        row = ctk.CTkFrame(outer, fg_color="transparent")
        row.pack(fill="x")
        
        if role == "user":
            # Аватар справа, пузырь прижат вправо
            if "user" in self.assets:
                ctk.CTkLabel(row, image=self.assets["user"], text="").pack(side="right", padx=(12, 0))
            else:
                ctk.CTkLabel(row, text="👤", font=ctk.CTkFont(size=28)).pack(side="right", padx=(12, 0))
            
            bubble = ctk.CTkFrame(row, fg_color=self.colors["bg_bubble_user"], corner_radius=20)
            bubble.pack(side="right", padx=(10, 0))
            
            ctk.CTkLabel(
                bubble, text=content, wraplength=700, justify="left",
                text_color="#ffffff", font=ctk.CTkFont(size=15), padx=18, pady=14
            ).pack()
        
        else:
            # Аватар слева, пузырь облегает контент (не растягивается на всё окно)
            if "assistant" in self.assets:
                ctk.CTkLabel(row, image=self.assets["assistant"], text="").pack(side="left", padx=(0, 14))
            else:
                ctk.CTkLabel(row, text="🤖", font=ctk.CTkFont(size=28)).pack(side="left", padx=(0, 14))
            
            bubble = ctk.CTkFrame(row, fg_color=self.colors["bg_bubble_ai"], corner_radius=20)
            bubble.pack(side="left")   # без fill="x" — пузырь по ширине контента
            
            answer_text = tk.Text(
                bubble,
                wrap="word",
                bg=self.colors["bg_bubble_ai"],
                fg=self.colors["text_primary"],
                font=("SF Pro Display", 14),
                borderwidth=0,
                highlightthickness=0,
                padx=20, pady=16,
                insertbackground=self.colors["bg_bubble_ai"],
                selectbackground=self.colors["accent"],
                selectforeground="#ffffff",
                cursor="arrow",
            )
            
            answer_text.pack(side="left")
            
            # САМОКАЛИБРОВКА ширины: меряем фактическую пиксельную ширину виджета
            target_px = min(950, _avail_width(row, 1200)) - 50
            answer_text.configure(width=80)
            answer_text.update_idletasks()
            w80 = answer_text.winfo_width()
            if w80 > 60:
                char_px = (w80 - 40) / 80.0          # фактическая ширина символа
                chars = max(40, int(target_px / char_px))
                answer_text.configure(width=chars)
                answer_text.update_idletasks()
            
            table_max = max(400, answer_text.winfo_width() - 60)
            
            embedded = render_markdown_to_text(answer_text, content, self.colors,
                                                 wheel_handler=self._on_mousewheel,
                                                 table_max=table_max)
            
            # Точная высота: сразу + отложенно (когда таблицы дорисуются)
            _fit_text_height(answer_text)
            answer_text.after(120, lambda w=answer_text: _fit_text_height(w))
            
            def _clear_selection(w=answer_text):
                w.tag_remove("sel", "1.0", "end")
                w.tag_remove("hl", "1.0", "end")
            
            def _ro_key(event, w=answer_text):
                kl = event.keysym.lower()
                is_cmd = bool(event.state & 0x40) or bool(event.state & 0x04)
                
                if kl in ('left', 'right', 'up', 'down', 'home', 'end',
                          'prior', 'next', 'page_up', 'page_down'):
                    return None
                
                if is_cmd and kl == 'c':
                    try:
                        sel = w.get("sel.first", "sel.last")
                        if sel:
                            set_clipboard_text(sel)
                            print(f"[DEBUG] Скопировано выделение: {sel[:40]}...")
                            _clear_selection()   # сняли выделение после копирования
                    except tk.TclError:
                        pass
                    return "break"
                
                if is_cmd and kl == 'a':
                    w.tag_add("sel", "1.0", "end")
                    w.event_generate("<KeyRelease>")  # обновить hl-подсветку
                    return "break"
                
                if kl == 'escape':
                    _clear_selection()
                    return "break"
                
                return "break"
            
            answer_text.bind("<Key>", _ro_key)
            
            def _do_copy(e=None, w=answer_text):
                try:
                    sel = w.get("sel.first", "sel.last")
                    if sel:
                        self._copy_text(sel)          # pbcopy + вспышка статуса сверху
                        w.tag_remove("sel", "1.0", "end")
                        w.tag_remove("hl", "1.0", "end")
                except tk.TclError:
                    pass
                return "break"
            
            answer_text.bind("<Command-c>", _do_copy)
            answer_text.bind("<Control-c>", _do_copy)
            answer_text.bind("<<Copy>>", _do_copy)
            answer_text.bind("<Command-a>", lambda e, w=answer_text: (w.tag_add("sel", "1.0", "end"), "break")[1])
            
            def _rmb(event, w=answer_text, full=content):
                try:
                    sel = w.get("sel.first", "sel.last")
                except tk.TclError:
                    sel = ""
                self._copy_text(sel if sel else full)
                _clear_selection()
                return "break"
            answer_text.bind("<Button-3>", _rmb)
            
            attach_visible_selection(answer_text, self.colors)
        
        self.messages_frame._parent_canvas.xview_moveto(0)
        self.messages_frame._parent_canvas.yview_moveto(1.0)
        
    def _copy_text(self, text: str):
        """Копирует текст в буфер обмена через pbcopy"""
        try:
            set_clipboard_text(text)
            print(f"Скопировано в буфер: {text[:50]}...")
            self.status_label.configure(text="Скопировано в буфер обмена", 
                                    text_color=self.colors["status_ready"])
            self.after(2000, lambda: self.status_label.configure(
                text="● Готов", text_color=self.colors["status_ready"]))
        except Exception as e:
            print(f"Ошибка копирования: {e}")
            
    def set_status(self, text: str, color: str = None):
        if color is None:
            color = self.colors["status_ready"]
        self.status_label.configure(text=text, text_color=color)
    
    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = THEMES[theme]
        self.configure(fg_color=self.colors["bg_main"])
        self.header.configure(fg_color="transparent")
        self.welcome_frame.configure(fg_color="transparent")
        self.messages_frame.configure(fg_color="transparent")
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
        input_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_input"], corner_radius=14)
        input_frame.pack(fill="x", padx=20, pady=12)
        
        self.textbox = tk.Text(
            input_frame, height=3, font=("SF Pro Display", 15), wrap="word",
            bg=self.colors["bg_input"], fg=self.colors["text_primary"],
            insertbackground=self.colors["text_primary"],
            selectbackground=self.colors["accent"], selectforeground="#ffffff",
            borderwidth=0, highlightthickness=0, padx=18, pady=14, relief="flat"
        )
        self.textbox.pack(side="left", fill="both", expand=True)
        
        self.textbox.bind("<Return>", self._on_enter)
        self.textbox.bind("<Shift-Return>", lambda e: None)
        
        # Явные bind'ы — они работают на macOS, когда <Key> не срабатывает для Cmd+X
        self.textbox.bind("<Command-v>", self._paste)
        self.textbox.bind("<Control-v>", self._paste)
        self.textbox.bind("<<Paste>>", self._paste)
        self.textbox.bind("<Command-c>", self._copy)
        self.textbox.bind("<Control-c>", self._copy)
        self.textbox.bind("<<Copy>>", self._copy)
        self.textbox.bind("<Command-x>", self._cut)
        self.textbox.bind("<Control-x>", self._cut)
        self.textbox.bind("<<Cut>>", self._cut)
        self.textbox.bind("<Command-a>", self._select_all)
        self.textbox.bind("<Control-a>", self._select_all)
        self.textbox.bind("<Button-3>", self._show_context_menu)
        
        self.textbox.insert("1.0", "Message RAG Assistant...")
        self.textbox.bind("<FocusIn>", self._on_focus_in)
        self.textbox.bind("<FocusOut>", self._on_focus_out)
        
        send_icon = self.assets.get("send")
        send_btn = ctk.CTkButton(
            input_frame, text="", image=send_icon if send_icon else None,
            command=self._handle_send, width=48, height=48,
            fg_color=self.colors["accent"], hover_color=self.colors["accent_hover"],
            font=ctk.CTkFont(size=22, weight="bold"), corner_radius=24
        )
        if not send_icon:
            send_btn.configure(text="↑", text_color="#ffffff")
        send_btn.pack(side="right", padx=(0, 12), pady=12)
        
        self.disclaimer_label = ctk.CTkLabel(
            self, text="Модель может ошибаться. Проверяйте важную информацию.",
            font=ctk.CTkFont(size=12), text_color=self.colors["text_secondary"]
        )
        self.disclaimer_label.pack(side="left", padx=20, pady=(0, 12))
    
    # ---------- служебные ----------
    def _clear_placeholder(self):
        if self.textbox.get("1.0", "end-1c").strip() == "Message RAG Assistant...":
            self.textbox.delete("1.0", "end")
    
    def _on_focus_in(self, event):
        self._clear_placeholder()
    
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
    
    # ---------- буфер обмена (pbpaste/pbcopy) ----------
    def _paste(self, event=None):
        text = get_clipboard_text()          # сначала через pbpaste
        if not text:                          # fallback: Tk-буфер (как в Edit->Paste)
            try:
                text = self.textbox.clipboard_get()
            except Exception:
                text = ""
        if text:
            current = self.textbox.get("1.0", "end-1c").strip()
            if current == "Message RAG Assistant...":
                self.textbox.delete("1.0", "end")
            self.textbox.insert("insert", text)
        return "break"
    
    def _copy(self, event=None):
        try:
            selection = self.textbox.get("sel.first", "sel.last")
            if selection:
                set_clipboard_text(selection)
                print(f"[DEBUG] Скопировано: {selection[:50]}")
        except tk.TclError:
            pass
        return "break"
    
    def _cut(self, event=None):
        try:
            selection = self.textbox.get("sel.first", "sel.last")
            if selection:
                set_clipboard_text(selection)
                self.textbox.delete("sel.first", "sel.last")
        except tk.TclError:
            pass
        return "break"
    
    def _select_all(self, event=None):
        self.textbox.tag_add("sel", "1.0", "end")
        return "break"
    
    def _show_context_menu(self, event):
        menu = tk.Menu(self, tearoff=0, bg=self.colors["bg_input"], fg=self.colors["text_primary"],
                       activebackground=self.colors["border"], activeforeground=self.colors["text_primary"])
        menu.add_command(label="Вырезать", command=self._cut)
        menu.add_command(label="Копировать", command=self._copy)
        menu.add_command(label="Вставить", command=self._paste)
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=self._select_all)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
     
    # ---------- прочее ----------
    def set_theme(self, theme: str):
        self.theme = theme
        self.colors = THEMES[theme]
        self.textbox.configure(
            bg=self.colors["bg_input"], fg=self.colors["text_primary"],
            insertbackground=self.colors["text_primary"],
            selectbackground=self.colors["accent"]
        )
        self.disclaimer_label.configure(text_color=self.colors["text_secondary"])
    
    def insert_text(self, text: str):
        self.textbox.delete("1.0", "end")
        self.textbox.insert("1.0", text)
        self.textbox.focus_set()
        
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
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
        self._create_macos_menu()  # ДОБАВЬ ЭТУ СТРОКУ
        self._load_current_chat()

    def _global_key_router(self, event):
        """Страховка: ловит Cmd/Ctrl+C,V,X,A на уровне окна, если виджетные bind'ы не сработали."""
        is_cmd = bool(event.state & 0x40) or bool(event.state & 0x04)
        if not is_cmd:
            return None
        k = event.keysym.lower()
        if k not in ('c', 'v', 'x', 'a'):
            return None
        
        w = self.focus_get()
        if not isinstance(w, tk.Text):
            return None
        
        is_input = (w is self.input_area.textbox)
        
        if k == 'v':
            if is_input:
                self.input_area._paste()
            return "break"
        if k == 'x':
            if is_input:
                self.input_area._cut()
            return "break"
        if k == 'c':
            try:
                sel = w.get("sel.first", "sel.last")
                if sel:
                    self.chat_area._copy_text(sel)    # pbcopy + вспышка статуса
                    w.tag_remove("sel", "1.0", "end")
                    w.tag_remove("hl", "1.0", "end")
            except tk.TclError:
                pass
            return "break"
        if k == 'a':
            w.tag_add("sel", "1.0", "end")
            return "break"
        return None

    def _load_assets(self):
        assets = {}
        
        logo = load_image_safe(ASSETS_DIR / "logo.png", (120, 120))
        if logo:
            assets["logo"] = logo
        
        for name in ["new_chat", "clear", "settings", "send"]:
            img = load_image_safe(ASSETS_DIR / "icons" / f"{name}.png", (32, 32))
            if img:
                assets[name] = img
        
        for name in ["user", "assistant"]:
            img = load_image_safe(ASSETS_DIR / "avatars" / f"{name}.png", (56, 56))
            if img:
                assets[name] = img
        
        bg = load_background_image(ASSETS_DIR / "background.png", (1920, 1080))
        if bg:
            assets["background"] = bg
        
        return assets
    
    def _build_ui(self):
        self.configure(fg_color=self.colors["bg_main"])
        
        self.sidebar = Sidebar(
            self,
            chat_manager=self.chat_manager,
            theme=self.theme,
            assets=self.assets,
            fg_color=self.colors["bg_sidebar"]
        )
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.set_app_ref(self)
        
        self.right_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_main"], corner_radius=0)
        self.right_frame.pack(side="right", fill="both", expand=True)
        
        self.chat_area = ChatArea(
            self.right_frame, 
            theme=self.theme, 
            assets=self.assets, 
            on_send_example=self._send_example,
            fg_color=self.colors["bg_main"]
        )
        self.chat_area.pack(fill="both", expand=True)
        
        self.input_area = InputArea(
            self.right_frame,
            theme=self.theme,
            assets=self.assets,
            on_send=self._send_message,
            fg_color=self.colors["bg_main"]
        )
        self.input_area.pack(fill="x", side="bottom")
        
        # БЕЗОПАСНАЯ глобальная привязка прокрутки к главному окну
        self.bind("<MouseWheel>", self._global_mousewheel)
        self.bind("<Button-4>", self._global_mousewheel)
        self.bind("<Button-5>", self._global_mousewheel)
        # Глобальная страховка горячих клавиш буфера обмена
        self.bind("<Key>", self._global_key_router)

    def _create_macos_menu(self):
        try:
            menubar = tk.Menu(self)
            edit_menu = tk.Menu(menubar, tearoff=0)
            edit_menu.add_command(label="Paste", accelerator="Cmd+V", command=self._global_paste)
            edit_menu.add_command(label="Copy", accelerator="Cmd+C", command=self._global_copy)
            edit_menu.add_command(label="Select All", accelerator="Cmd+A", command=self._global_select_all)
            menubar.add_cascade(label="Edit", menu=edit_menu)
            self.config(menu=menubar)
        except Exception as e:
            print(f"[DEBUG] Не удалось создать меню: {e}")


    def _global_paste(self, event=None):
        if hasattr(self, 'input_area'):
            self.input_area._paste()
        return "break"
    
    def _global_copy(self, event=None):
        w = self.focus_get()
        if isinstance(w, tk.Text):
            try:
                sel = w.get("sel.first", "sel.last")
                if sel:
                    set_clipboard_text(sel)
                    w.tag_remove("sel", "1.0", "end")
                    w.tag_remove("hl", "1.0", "end")
                    return "break"
            except tk.TclError:
                pass
        return "break"

    def _global_select_all(self, event=None):
        if hasattr(self, 'input_area') and hasattr(self.input_area, 'textbox'):
            self.input_area.textbox.tag_add("sel", "1.0", "end")
            self.input_area.textbox.focus_set()
        return "break"
    
    def _global_mousewheel(self, event):
        """Безопасная глобальная обработка прокрутки"""
        if hasattr(self, 'chat_area') and hasattr(self.chat_area, 'messages_frame'):
            if event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
                self.chat_area.messages_frame._parent_canvas.yview_scroll(1, "units")
            elif event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
                self.chat_area.messages_frame._parent_canvas.yview_scroll(-1, "units")
    
    def _send_example(self, text: str):
        self.input_area.insert_text(text)
        self.input_area._handle_send()
    
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
        # Сброс флага на всякий случай (защита от зависания)
        if self.is_processing:
            self.is_processing = False
            return
        
        self.chat_area.show_messages()
        self.chat_area.add_message("user", user_input)
        self.chat_manager.add_message("user", user_input)
        
        chat = self.chat_manager.get_current_chat()
        if chat and chat["name"] == "Новый чат" and len(chat["messages"]) == 1:
            new_name = user_input[:30] + ("..." if len(user_input) > 30 else "")
            self.chat_manager.rename_chat(self.chat_manager.current_chat_id, new_name)
            self.sidebar.update_chat_list()
        
        self.is_processing = True
        self.chat_area.set_status("● Думаю...", self.colors["status_busy"])
        
        threading.Thread(target=self._process, args=(user_input,), daemon=True).start()
    
    def _process(self, user_input: str):
        try:
            if self.rag_system is None:
                self.chat_area.set_status("● Загрузка модели...", self.colors["status_busy"])
                self.rag_system = SmartRAG()
            
            self.chat_area.set_status("● Поиск в базе...", self.colors["status_busy"])
            response = self.rag_system.query(user_input)
            clean = response.replace("[С поиском]:\n", "").replace("[Без поиска]: ", "")
            
            self.after(0, self.chat_area.add_message, "assistant", clean)
            self.chat_manager.add_message("assistant", clean)
            self.chat_area.set_status("● Готов", self.colors["status_ready"])
            self.is_processing = False
            
        except Exception as e:
            err = f"Ошибка: {str(e)}"
            self.after(0, self.chat_area.add_message, "assistant", err)
            self.chat_area.set_status("● Ошибка", self.colors["status_error"])
            self.is_processing = False


if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = AviationRAGApp()
    app.mainloop()