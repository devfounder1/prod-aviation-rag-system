import os 
from pathlib import Path
from typing import Optional
from langchain_core.tools import tool 
import subprocess
import tempfile

AGENT_WORKSPACE = Path(__file__).parent / "agent_workspace"
AGENT_WORKSPACE.mkdir(exist_ok=True)

DANGEROUS_IMPORTS = [
    'os.system', 'os.popen', 'subprocess', 'shutil.rmtree', 
    'evsl(', 'exec(', '__import__', 'importlib'
]

DANGEROUS_MODULES = [
    'os', 'subprocess', 'shutil', 'sys', 'ctypes', 'socet',
    'requests', 'urllib', 'http'
]

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
        
        return content
    
    except Exception as e:
        return f"Ошибка чтения файла: {str(e)}"


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
        
        # Записываем файл
        full_path.write_text(content, encoding='utf-8')
        
        return f"Файл успешно записан: {file_path} ({len(content)} символов)"
    
    except Exception as e:
        return f"Ошибка записи файла: {str(e)}"


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
            return f"Директория пуста: {directory_path}"
        
        return "\n".join(items)
    
    except Exception as e:
        return f"Ошибка чтения директории: {str(e)}"


@tool
def execute_python_code(code: str, timeout: int = 10) -> str:
    """
    Выполняет Python-код в безопасной изолированной среде.
    
    ВАЖНО: 
    - Код выполняется в рабочей директории агента
    - Максимальное время выполнения: timeout секунд (по умолчанию 10)
    - Запрещены опасные импорты (os, subprocess, shutil и т.д.)
    - Вывод ограничен первыми 2000 символами
    
    Args:
        code: Python-код для выполнения
        timeout: Максимальное время выполнения в секундах (по умолчанию 10)
    
    Returns:
        Результат выполнения (stdout) или сообщение об ошибке
    """
    try:
        # Проверка на запрещённые импорты
        for dangerous in DANGEROUS_IMPORTS:
            if dangerous in code:
                return f"Ошибка безопасности: Использование '{dangerous}' запрещено"
        
        for module in DANGEROUS_MODULES:
            if f"import {module}" in code or f"from {module}" in code:
                return f"Ошибка безопасности: Импорт модуля '{module}' запрещён"
        
        # Создаём временный файл для кода
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix='.py', 
            dir=AGENT_WORKSPACE,
            delete=False,
            encoding='utf-8'
        ) as f:
            f.write(code)
            temp_file = f.name
        
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
                output.append(result.stdout[:2000])  # Ограничение вывода
                if len(result.stdout) > 2000:
                    output.append(f"\n... [Вывод обрезан, показано {2000} из {len(result.stdout)} символов]")
            
            if result.stderr:
                output.append("\n=== STDERR (Ошибки) ===")
                output.append(result.stderr[:2000])
            
            if result.returncode != 0:
                output.append(f"\nКод завершился с ошибкой (код возврата: {result.returncode})")
            
            if not output:
                return "Код выполнен успешно (нет вывода)"
            
            return "\n".join(output)
        
        except subprocess.TimeoutExpired:
            return f"Таймаут: Код выполнялся дольше {timeout} секунд и был прерван"
        
        finally:
            # Удаляем временный файл
            try:
                os.unlink(temp_file)
            except:
                pass
    
    except Exception as e:
        return f"Ошибка выполнения кода: {str(e)}"


# Список всех доступных инструментов
ALL_TOOLS = [
    read_file,
    write_file,
    list_directory,
    execute_python_code,
]       