"""Фоновые потоки (QThread): запись аудио и загрузка заметок."""

from PySide6.QtCore import (
    QThread,
    Signal,
)

import logging


class AudioRecorderThread(QThread):
    recording_finished = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self._running = True
        self._wavefile = None

    def callback(self, indata, frames, time, status):
        if self._running and self._wavefile:
            self._wavefile.writeframes(indata.tobytes())

    def run(self):
        try:
            import sounddevice as sd

            import wave
            with wave.open(self.file_path, "wb") as wf:
                self._wavefile = wf
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                with sd.InputStream(
                    samplerate=44100,
                    channels=1,
                    dtype="int16",
                    callback=self.callback,
                ):
                    while self._running:
                        sd.sleep(100)
            self.recording_finished.emit(self.file_path)
        except Exception:
            logging.exception("Audio record failed: %s", self.file_path)
        finally:
            self._wavefile = None

    def stop(self):
        self._running = False


class NotesLoaderThread(QThread):
    finished = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self) -> None:
        try:
            from noteapp.app import NotesApp  # локальный импорт: разрыв цикла
            notes = NotesApp.read_notes_snapshot()
        except Exception:
            notes = []
        self.finished.emit(notes)
