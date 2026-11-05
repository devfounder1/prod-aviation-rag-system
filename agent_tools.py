import os 
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool 
import subprocess
import tempfile
import json
from datetime import datetime

AGENT_WORKSPACE = Path(__file__).parent / "agent_workspace"
AGENT_WORKSPACE.mkdir(exist_ok=True)

DANGEROUS_IMPORTS = [
    'os.system', 'os.popen', 'subprocess', 'shutil.rmtree', 
    'eval(', 'exec(', '__import__', 'importlib'  
]

DANGEROUS_MODULES = [
    'os', 'subprocess', 'shutil', 'sys', 'ctypes', 'socket',  # ✅ socket
    'requests', 'urllib', 'http'
]

# ЛОГГЕР АГЕНТА
class AgentLogger:
    """Логирует все действия агента в файл"""
    
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Создаём файл с заголовком
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"Сессия агента: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*80}\n\n")
    
    def log_tool_call(self, tool_name: str, args: dict, result: str, duration: float = 0):
        """Логирует вызов инструмента"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        log_entry = {
            "timestamp": timestamp,
            "tool": tool_name,
            "args": args,
            "result": result[:500],  # Обрезаем длинные результаты
            "duration_seconds": round(duration, 2)
        }
        
        # Записываем в файл
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] {tool_name}\n")
            f.write(f"  Аргументы: {json.dumps(args, ensure_ascii=False)[:200]}\n")
            f.write(f"  Результат: {result[:300]}...\n")
            f.write(f"  Время: {duration:.2f}с\n\n")
        
        # Также выводим в консоль
        print(f"[AGENT LOG] {tool_name}: {result[:100]}...", flush=True)

# Глобальный логгер
agent_logger = AgentLogger(AGENT_WORKSPACE / "agent_log.txt")
# CALLBACK ДЛЯ ПОДТВЕРЖДЕНИЯ КОДА
_code_approval_callback = None

def set_approval_callback(callback):
    """Устанавливает callback для подтверждения кода (вызывается из prilozhenie.py)"""
    global _code_approval_callback
    _code_approval_callback = callback

# CALLBACK ДЛЯ ПОИСКА В БАЗЕ ЗНАНИЙ
_knowledge_search_callback = None

def set_knowledge_search_callback(callback):
    global _knowledge_search_callback
    _knowledge_search_callback = callback


@tool
def search_knowledge_base(query: str) -> str:
    """
    Ищет информацию в базе технической документации ПРЛ-27СМ.
    ИСПОЛЬЗУЙ, если задача упоминает оборудование, протоколы, сигналы, интерфейсы.
    
    Args:
        query: Поисковый запрос на русском языке
    
    Returns:
        Фрагменты найденной документации с указанием источников
    """
    if not _knowledge_search_callback:
        return "Ошибка: База знаний недоступна"
    result = _knowledge_search_callback(query)
    agent_logger.log_tool_call("search_knowledge_base", {"query": query}, result)
    return result

# РЕЕСТР ПРИКРЕПЛЁННЫХ КОД-ФАЙЛОВ: имя -> оригинальный путь на диске
_attached_code_files = {}

def register_attached_file(name: str, original_path: str):
    """Регистрирует прикреплённый код-файл (вызывается из prilozhenie.py)"""
    _attached_code_files[name] = original_path
    print(f"[AGENT] Зарегистрирован код-файл: {name} -> {original_path}", flush=True)


@tool
def update_attached_file(file_name: str, new_content: str) -> str:
    """
    Обновляет содержимое ПРИКРЕПЛЁННОГО пользователем код-файла.
    Изменения записываются в ОРИГИНАЛЬНЫЙ файл на диске (создаётся .bak-бэкап).
    Перед записью пользователь видит новый контент и подтверждает изменение.
    
    Args:
        file_name: Имя прикреплённого файла (например, 'script.py')
        new_content: Новое ПОЛНОЕ содержимое файла
    
    Returns:
        Сообщение об успехе или отклонении изменения
    """
    if file_name not in _attached_code_files:
        available = ", ".join(_attached_code_files.keys()) or "нет"
        return f"Ошибка: файл '{file_name}' не прикреплён. Прикреплены: {available}"
    
    original = _attached_code_files[file_name]
    
    print(f"\n[AGENT TOOLS] ЗАПИСЬ В ФАЙЛ {file_name}:", flush=True)
    print("="*60, flush=True)
    print(new_content, flush=True)
    print("="*60, flush=True)
    
    # Обязательное подтверждение пользователем (ВСЕГДА для сохранения файлов)
    if _code_approval_callback:
        approved = _code_approval_callback(
            f"--- ФИНАЛЬНЫЙ ПРОВЕРЕННЫЙ КОД ФАЙЛА {file_name} ---\n{new_content}"
        )
        if not approved:
            result = f"❌ Пользователь отклонил изменения файла {file_name}"
            agent_logger.log_tool_call("update_attached_file", {"file_name": file_name}, result)
            return result
    
    try:
        # Бэкап оригинала перед перезаписью
        orig_path = Path(original)
        backup = orig_path.with_suffix(orig_path.suffix + ".bak")
        if not backup.exists():
            backup.write_text(orig_path.read_text(encoding='utf-8'), encoding='utf-8')
        
        # Пишем изменения в оригинал
        orig_path.write_text(new_content, encoding='utf-8')
        
        # Синхронизируем копию в workspace
        attached_copy = AGENT_WORKSPACE / "attached" / file_name
        if attached_copy.parent.exists():
            attached_copy.write_text(new_content, encoding='utf-8')
        
        result = f"Файл {file_name} обновлён. Бэкап оригинала: {backup.name}"
        agent_logger.log_tool_call("update_attached_file", {"file_name": file_name, "len": len(new_content)}, result)
        return result
    except Exception as e:
        result = f"Ошибка обновления файла: {str(e)}"
        agent_logger.log_tool_call("update_attached_file", {"file_name": file_name}, result)
        return result

@tool
def read_file(file_path: str) -> str:
    """
    Читает содержимое файла из рабочей директории агента.
    
    Args:
        file_path: Путь к файлу (относительно рабочей директории или абсолютный)
    
    Returns:
        Содержимое файла или сообщение об ошибке
    """
    try: 
        full_path = AGENT_WORKSPACE / file_path if not Path(file_path).is_absolute() else Path(file_path)
        
        try: 
            full_path.resolve().relative_to(AGENT_WORKSPACE.resolve())
        except ValueError:
            return f"Ошибка: Доступ к файлу вне рабочей директории запрещён: {file_path}"
        
        if not full_path.exists():
            return f"Ошибка: Файл не найден: {file_path}"
        
        if full_path.is_dir():
            return f"Ошибка: Это директория, а не файл: {file_path}"
        
        # Читаем файл (ограничение 50KB)
        content = full_path.read_text(encoding='utf-8', errors='ignore')
        if len(content) > 50000:
            content = content[:50000] + "\n\n... [Файл обрезан, слишком большой]"
        
        agent_logger.log_tool_call("read_file", {"file_path": file_path}, content)  # 🆕 Логируем успех
        return content
    
    except Exception as e:
        result = f"Ошибка чтения файла: {str(e)}"
        agent_logger.log_tool_call("read_file", {"file_path": file_path}, result)
        return result


@tool
def write_file(file_path: str, content: str) -> str:
    """
    Записывает содержимое в файл в рабочей директории агента.
    
    Args:
        file_path: Путь к файлу (относительно рабочей директории)
        content: Содержимое для записи
    
    Returns:
        Сообщение об успехе или ошибке
    """
    try:
        full_path = AGENT_WORKSPACE / file_path
        
        # Создаём родительские директории
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        full_path.write_text(content, encoding='utf-8')
        
        result = f"Файл успешно записан: {file_path} ({len(content)} символов)"
        agent_logger.log_tool_call("write_file", {"file_path": file_path, "content_length": len(content)}, result)  # 🆕 Логируем успех
        return result
    
    except Exception as e:
        result = f"Ошибка записи файла: {str(e)}"
        agent_logger.log_tool_call("write_file", {"file_path": file_path, "content_length": len(content)}, result)  # 🆕 Исправлено имя инструмента
        return result

@tool
def list_directory(directory_path: str = ".") -> str:
    """
    Показывает содержимое директории в рабочей области агента.
    
    Args:
        directory_path: Путь к директории (по умолчанию корень рабочей области)
    
    Returns:
        Список файлов и директорий
    """
    try:
        full_path = AGENT_WORKSPACE / directory_path
        
        # Защита от выхода за пределы
        try:
            full_path.resolve().relative_to(AGENT_WORKSPACE.resolve())
        except ValueError:
            return f"Ошибка: Доступ к директории вне рабочей области запрещён"
        
        if not full_path.exists():
            return f"Ошибка: Директория не найдена: {directory_path}"
        
        if not full_path.is_dir():
            return f"Ошибка: Это файл, а не директория: {directory_path}"
        
        # Получаем список файлов
        items = []
        for item in sorted(full_path.iterdir()):
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = item.stat().st_size
                items.append(f"📄 {item.name} ({size} байт)")
        
        if not items:
            result = f"Директория пуста: {directory_path}"
            agent_logger.log_tool_call("list_directory", {"directory_path": directory_path}, result)
            return result
        
        result = "\n".join(items)
        agent_logger.log_tool_call("list_directory", {"directory_path": directory_path}, result)  # 🆕 Логируем успех
        return result
    
    except Exception as e:
        result = f"Ошибка чтения директории: {str(e)}"
        agent_logger.log_tool_call("list_directory", {"directory_path": directory_path}, result)  # 🆕 Исправлено: directory_path вместо file_path
        return result

@tool
def execute_python_code(code: str, timeout: int = 10, require_approval: bool = True) -> str:
    """
    Выполняет Python-код в безопасной изолированной среде.
    
    ВАЖНО: 
    - Если require_approval=True (по умолчанию), пользователь увидит код и должен его одобрить.
    - Если require_approval=False, код выполнится мгновенно в фоне (ИСПОЛЬЗУЙ ЭТО ТОЛЬКО ДЛЯ ВНУТРЕННЕГО ТЕСТИРОВАНИЯ ПЕРЕД СОХРАНЕНИЕМ).
    - Максимальное время выполнения: timeout секунд.
    - Запрещены опасные импорты.
    
    Args:
        code: Python-код для выполнения
        timeout: Максимальное время выполнения в секундах (по умолчанию 10)
        require_approval: Требовать ли одобрения пользователя (по умолчанию True)
    
    Returns:
        Результат выполнения (stdout) или сообщение об ошибке
    """
    import time
    start_time = time.time()
    
    try:
        # Проверка на запрещённые импорты
        for dangerous in DANGEROUS_IMPORTS:
            if dangerous in code:
                result = f"Ошибка безопасности: Использование '{dangerous}' запрещено"
                agent_logger.log_tool_call("execute_python_code", {"code": code[:100]}, result)
                return result
        
        for module in DANGEROUS_MODULES:
            if f"import {module}" in code or f"from {module}" in code:
                result = f"Ошибка безопасности: Импорт модуля '{module}' запрещён"
                agent_logger.log_tool_call("execute_python_code", {"code": code[:100]}, result)
                return result
        
        # ЗАПРОС ПОДТВЕРЖДЕНИЯ (ТОЛЬКО если require_approval=True)
        if require_approval and _code_approval_callback:
            approved = _code_approval_callback(code)
            if not approved:
                result = "Выполнение кода отменено пользователем"
                agent_logger.log_tool_call("execute_python_code", {"code": code[:100], "require_approval": True}, result)
                return result
        
        # УМНАЯ СОРТИРОВКА: внутренние тесты прячем в папку debug, финальные скрипты оставляем в scripts
        if not require_approval:
            SCRIPTS_DIR = AGENT_WORKSPACE / "scripts" / "debug_tests"
        else:
            SCRIPTS_DIR = AGENT_WORKSPACE / "scripts"
            
        SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        script_name = f"script_{datetime.now().strftime('%Y%m%d_%H%M%S')}.py"
        script_path = SCRIPTS_DIR / script_name
        script_path.write_text(code, encoding='utf-8')
        temp_file = str(script_path)
        
        try:
            # Выполняем код с таймаутом
            result = subprocess.run(
                ['python', temp_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(AGENT_WORKSPACE),
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )
            
            # Формируем вывод
            output = []
            
            if result.stdout:
                output.append("=== STDOUT ===")
                output.append(result.stdout[:2000])
                if len(result.stdout) > 2000:
                    output.append(f"\n... [Вывод обрезан]")
            
            if result.stderr:
                output.append("\n=== STDERR (Ошибки) ===")
                output.append(result.stderr[:2000])
            
            if result.returncode != 0:
                output.append(f"\nКод завершился с ошибкой (код возврата: {result.returncode})")
            
            final_output = "\n".join(output) if output else "Код выполнен успешно (нет вывода)"
            final_output += f"\n\n💾 Скрипт сохранён: scripts/{script_name}"  # 🆕
            
            # Логируем
            duration = time.time() - start_time
            agent_logger.log_tool_call("execute_python_code", {"code": code[:200]}, final_output, duration)
            
            return final_output
        
        except subprocess.TimeoutExpired:
            result = f"Таймаут: Код выполнялся дольше {timeout} секунд и был прерван"
            duration = time.time() - start_time
            agent_logger.log_tool_call("execute_python_code", {"code": code[:100]}, result, duration)
            return result
        
        finally:
            pass 
        
    except Exception as e:
        result = f"Ошибка выполнения кода: {str(e)}"
        duration = time.time() - start_time
        agent_logger.log_tool_call("execute_python_code", {"code": code[:100]}, result, duration)
        return result


ALL_TOOLS = [
    read_file,
    write_file,
    list_directory,
    execute_python_code,
    search_knowledge_base,
    update_attached_file,   # 🆕
]      