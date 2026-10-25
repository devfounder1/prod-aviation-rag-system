from pathlib import Path
from document_processor import add_document, list_documents, retrieve_user_context

p = Path("sample_test.txt")
p.write_text(
    "Сигнал PPS генерируется модулем ПС-161 и передаётся на МКУ по интерфейсу RS-232.\n\n"
    "Частота сигнала PPS составляет 1 раз в секунду.\n\n"
    "Задержка выдачи сигнала PPS2 может быть задана с точностью до 1 мс.",
    encoding="utf-8")

print(add_document(p))
print("СПИСОК:", list_documents())
print("ПОИСК:\n", retrieve_user_context("Какая частота у сигнала PPS?"))
