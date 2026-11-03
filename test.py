# test_tools.py
from agent_tools import read_file, write_file, list_directory, execute_python_code

# Тест 1: Запись файла
result = write_file.invoke({"file_path": "test.txt", "content": "Привет, мир!"})
print("1. Запись:", result)

# Тест 2: Чтение файла
result = read_file.invoke({"file_path": "test.txt"})
print("2. Чтение:", result)

# Тест 3: Список директории
result = list_directory.invoke({"directory_path": "."})
print("3. Список:", result)

# Тест 4: Выполнение кода
code = """
print("Сумма 2+2 =", 2+2)
for i in range(3):
    print(f"Итерация {i}")
"""
result = execute_python_code.invoke({"code": code})
print("4. Выполнение:", result)

# Тест 5: Безопасность (должен быть запрещён)
result = execute_python_code.invoke({"code": "import os; print(os.system('ls'))"})
print("5. Безопасность:", result)