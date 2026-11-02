from faster_whisper import WhisperModel

for name in ("base", "small"):
    for attempt in range(3):
        try:
            print(f"⬇️  Качаю модель {name} (попытка {attempt + 1})...", flush=True)
            WhisperModel(name, device="cpu", compute_type="int8")
            print(f"✅ {name} готова", flush=True)
            break
        except Exception as e:
            print(f"⚠️ Ошибка: {e}", flush=True)
    else:
        print(f"❌ Не удалось скачать {name}", flush=True)

print("🎉 Всё готово, можно запускать приложение")