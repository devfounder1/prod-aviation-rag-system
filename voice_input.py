"""
Голосовой ввод: запись с микрофона, транскрипция faster-whisper, wake-word «Бутуз».
"""
import threading
import time
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
WAKE_WORDS = (
    "бутуз", "бутуза", "путуз", "бутус", "будус", "бутусь", "будуз",
    "будусь", "ампетус", "бит", "готовь"  # добавь всё, что слышит модель
)

_transcriber_lock = threading.Lock()
_transcriber = None

def _fuzzy_match(heard: str, targets: tuple) -> bool:
    """Проверяет, похоже ли услышанное слово на одно из целевых"""
    from difflib import SequenceMatcher
    
    heard_clean = heard.strip().lower().replace(" ", "")
    for target in targets:
        # Точное вхождение
        if target in heard_clean:
            return True
        # Похожесть > 0.7 (например "бутуз" и "будусь" похожи на 0.8)
        ratio = SequenceMatcher(None, heard_clean, target).ratio()
        if ratio > 0.7:
            return True
    return False

def _load_with_retry(factory, attempts=3, delay=5):
    import time
    for i in range(attempts):
        try:
            return factory()
        except Exception as e:
            print(f"[VOICE] Ошибка загрузки модели (попытка {i + 1}): {e}", flush=True)
            if i == attempts - 1:
                raise
            time.sleep(delay)


def get_transcriber():
    """Ленивая загрузка моделей whisper (один раз на процесс)"""
    global _transcriber
    with _transcriber_lock:
        if _transcriber is None:
            from faster_whisper import WhisperModel
            print("[VOICE] Загрузка моделей whisper...", flush=True)
            wake = _load_with_retry(lambda: WhisperModel("base", device="cpu", compute_type="int8"))  # для wake-word (быстро)
            main = _load_with_retry(lambda: WhisperModel("small", device="cpu", compute_type="int8"))  # для команд (точно)
            _transcriber = (wake, main)
            print("[VOICE] Модели whisper готовы", flush=True)
        return _transcriber


def transcribe(audio: np.ndarray, model_kind: str = "main") -> str:
    """Распознаёт речь из numpy-массива (float32, 16kHz, mono)"""
    wake, main = get_transcriber()
    model = wake if model_kind == "wake" else main
    segments, _ = model.transcribe(audio, language="ru", beam_size=1, vad_filter=False)
    return " ".join(s.text.strip() for s in segments).lower()


def record_until_stop(stop_event: threading.Event, max_seconds: float = 60.0, block: float = 0.2) -> np.ndarray:
    """Пишет звук, пока не выставлен stop_event (режим кнопки-тумблера)"""
    chunks = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        elapsed = 0.0
        while not stop_event.is_set() and elapsed < max_seconds:
            data, _ = stream.read(int(block * SAMPLE_RATE))
            chunks.append(data.squeeze())
            elapsed += block
    if not chunks:
        return np.zeros(SAMPLE_RATE, dtype="float32")
    return np.concatenate(chunks)


def record_until_silence(max_seconds: float = 12.0, silence_threshold: float = 0.01,
                         silence_duration: float = 1.2, no_speech_timeout: float = 4.0,
                         block: float = 0.3) -> np.ndarray:
    """Пишет команду: старт по речи, стоп по паузе (режим wake-word)"""
    chunks = []
    silence_blocks = int(silence_duration / block)
    max_blocks = int(max_seconds / block)
    no_speech_blocks = int(no_speech_timeout / block)
    heard_speech = False
    quiet_run = 0
    quiet_total = 0
    
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32") as stream:
        for _ in range(max_blocks):
            data, _ = stream.read(int(block * SAMPLE_RATE))
            chunk = data.squeeze()
            chunks.append(chunk)
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if rms > silence_threshold:
                heard_speech = True
                quiet_run = 0
            else:
                quiet_total += 1
                if heard_speech:
                    quiet_run += 1
                    if quiet_run >= silence_blocks:
                        break
                elif quiet_total >= no_speech_blocks:
                    break  # так и не заговорили
    
    if not chunks:
        return np.zeros(SAMPLE_RATE, dtype="float32")
    return np.concatenate(chunks)


class WakeWordListener:
    """Фоновый слушатель: ждёт фразу «Бутуз» в потоке речи"""
    
    def __init__(self, on_wake):
        self.on_wake = on_wake
        self._stop = threading.Event()
        self.paused = threading.Event()  # ставится, пока пишем команду
        self._thread = None
    
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        self._stop.set()
    
    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()
    
    def _loop(self):
        print("[VOICE] Wake-listener запущен: жду «Бутуз»...", flush=True)
        while not self._stop.is_set():
            if self.paused.is_set():
                time.sleep(0.5)
                continue
            
            # ТЕПЕРЬ ЭТО ВНУТРИ ЦИКЛА (правильные отступы!)
            try:
                chunk = record_until_stop_stopless(2.0)
                text = transcribe(chunk, model_kind="wake")
                # Очищаем от пробелов, знаков препинания и приводим к нижнему регистру
                clean_text = text.strip().lower().strip(".,!?;: ")
                #print(f"[VOICE] Услышал: '{clean_text}'", flush=True)
                
                if clean_text and _fuzzy_match(clean_text, WAKE_WORDS):
                    print(f"[VOICE] Wake-word распознан (fuzzy): '{clean_text}'", flush=True)
                    self.on_wake()
                elif clean_text:
                    # Если что-то распознано, но не наш wake-word — логируем для отладки
                    pass
            except Exception as e:
                print(f"[VOICE] Ошибка wake-listener: {e}", flush=True)
                time.sleep(2)
        
        print("[VOICE] Wake-listener остановлен", flush=True)


def record_until_stop_stopless(seconds: float) -> np.ndarray:
    """Просто пишет N секунд (для wake-listener)"""
    frames = int(seconds * SAMPLE_RATE)
    data = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return data.squeeze()