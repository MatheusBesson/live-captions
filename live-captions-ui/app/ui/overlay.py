"""
Overlay de legendas — janela principal do app.

Características:
- Frameless e sempre visível sobre qualquer janela (Meet, YouTube etc.)
- Fundo semi-transparente arrastável pelo usuário
- Exibe legenda original (cinza) e traduzida (branca)
- Seletor de idioma alvo embutido
- Botão de pausa e configurações
"""

from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QPalette, QCursor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSizeGrip, QFrame,
)

import requests

from app.audio.capture import AudioCapture
from app.audio.device_detector import AudioDevice
from app.config import SUPPORTED_LANGUAGES, API_TRANSCRIBE


# ── Worker Thread (requisição ao backend) ─────────────────────────────────────

class TranscribeWorker(QObject):
    """
    Envia chunks de áudio ao Spring Boot e emite o resultado.
    Roda em QThread para não bloquear a UI.
    """
    result_ready = pyqtSignal(str, str)    # (original, translated)
    error_occurred = pyqtSignal(str)

    def __init__(self, target_language: str):
        super().__init__()
        self.target_language = target_language

    def transcribe(self, audio_b64: str):
        """Chamado pela thread — envia áudio ao backend e emite resultado."""
        try:
            payload = {
                "audio": audio_b64,
                "targetLanguage": self.target_language,
                "sampleRate": 16000,
            }
            response = requests.post(API_TRANSCRIBE, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            original = data.get("original", "")
            translated = data.get("translated", original)
            self.result_ready.emit(original, translated)
        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("Backend offline — iniciando Spring Boot?")
        except requests.exceptions.Timeout:
            self.error_occurred.emit("Timeout ao conectar com o backend.")
        except Exception as e:
            self.error_occurred.emit(f"Erro: {e}")


# ── Overlay Window ─────────────────────────────────────────────────────────────

class OverlayWindow(QWidget):
    def __init__(self, device: AudioDevice):
        super().__init__()
        self._device = device
        self._drag_pos: QPoint | None = None
        self._is_paused = False
        self._target_lang = "en"

        self._capture: AudioCapture | None = None
        self._worker: TranscribeWorker | None = None
        self._thread: QThread | None = None

        self._setup_window()
        self._setup_ui()
        self._setup_audio()

    # ── Janela ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool               # não aparece na barra de tarefas
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(500)
        self.setMinimumHeight(120)
        self.resize(600, 160)

    def _setup_ui(self):
        self.setStyleSheet("""
            QWidget#bg {
                background: rgba(10, 10, 10, 210);
                border-radius: 14px;
                border: 1px solid rgba(255,255,255,0.08);
            }
            QLabel#caption-translated {
                color: #ffffff;
                font-size: 22px;
                font-weight: 500;
                font-family: sans-serif;
            }
            QLabel#caption-original {
                color: #888888;
                font-size: 13px;
                font-family: sans-serif;
            }
            QLabel#status {
                color: #555;
                font-size: 11px;
                font-family: monospace;
            }
            QPushButton {
                background: transparent;
                border: none;
                color: #666;
                font-size: 16px;
                padding: 4px 8px;
                border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.08); color: #ccc; }
            QComboBox {
                background: rgba(255,255,255,0.06);
                border: 1px solid rgba(255,255,255,0.12);
                border-radius: 6px;
                color: #aaa;
                font-size: 12px;
                padding: 3px 8px;
                min-width: 100px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1a1a1a;
                border: 1px solid #333;
                selection-background-color: #2d5a8e;
                color: #e0e0e0;
            }
        """)

        # Container com fundo — necessário para TranslucentBackground funcionar
        bg = QWidget(self, objectName="bg")
        bg.setGeometry(0, 0, self.width(), self.height())
        self._bg = bg

        outer = QVBoxLayout(bg)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(4)

        # ── Barra superior (controles) ────────────────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        # Indicador de status
        self._status_label = QLabel("● ouvindo", objectName="status")
        self._status_label.setStyleSheet("color: #3a9e6a; font-size: 11px;")
        top_bar.addWidget(self._status_label)

        top_bar.addStretch()

        # Seletor de idioma alvo
        lang_hint = QLabel("traduzir para:")
        lang_hint.setStyleSheet("color: #555; font-size: 11px;")
        top_bar.addWidget(lang_hint)

        self._lang_combo = QComboBox()
        for name, code in SUPPORTED_LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        # Padrão: English
        idx = list(SUPPORTED_LANGUAGES.values()).index("en")
        self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top_bar.addWidget(self._lang_combo)

        # Botão pausa
        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setToolTip("Pausar / Retomar")
        self._pause_btn.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self._pause_btn)

        # Botão fechar
        close_btn = QPushButton("✕")
        close_btn.setToolTip("Fechar")
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(close_btn)

        outer.addLayout(top_bar)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.06);")
        outer.addWidget(sep)

        # ── Área de legenda ───────────────────────────────────────────────────
        self._caption_original = QLabel("", objectName="caption-original")
        self._caption_original.setWordWrap(True)
        self._caption_original.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption_original.hide()
        outer.addWidget(self._caption_original)

        self._caption_main = QLabel("Aguardando áudio...", objectName="caption-translated")
        self._caption_main.setWordWrap(True)
        self._caption_main.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._caption_main)

        outer.addStretch()

    # ── Áudio e backend ───────────────────────────────────────────────────────

    def _setup_audio(self):
        # Worker em thread separada para não bloquear a UI
        self._thread = QThread()
        self._worker = TranscribeWorker(target_language=self._target_lang)
        self._worker.moveToThread(self._thread)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._thread.start()

        # Captura de áudio — chama _on_audio_chunk a cada CHUNK_DURATION segundos
        self._capture = AudioCapture(
            device=self._device, #device_index=self._device.index
            on_chunk=self._on_audio_chunk,
        )
        self._capture.start()
        self._set_status("● ouvindo", "#3a9e6a")

    def _on_audio_chunk(self, audio_b64: str):
        """Chamado pela thread de áudio — repassa ao worker via Qt signal."""
        if not self._is_paused:
            # Invoke na thread do worker (thread-safe)
            self._worker.transcribe(audio_b64)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_result(self, original: str, translated: str):
        if not original.strip():
            return
        show_original = original != translated
        if show_original:
            self._caption_original.setText(original)
            self._caption_original.show()
        else:
            self._caption_original.hide()
        self._caption_main.setText(translated)

    def _on_error(self, msg: str):
        self._caption_main.setText(msg)
        self._caption_main.setStyleSheet("color: #e05a5a; font-size: 16px;")

    def _on_language_changed(self, idx: int):
        self._target_lang = self._lang_combo.currentData()
        if self._worker:
            self._worker.target_language = self._target_lang

    def _toggle_pause(self):
        self._is_paused = not self._is_paused
        if self._is_paused:
            self._pause_btn.setText("▶")
            self._set_status("⏸ pausado", "#888")
            self._caption_main.setStyleSheet(
                "color: #666; font-size: 22px; font-weight: 500;"
            )
        else:
            self._pause_btn.setText("⏸")
            self._set_status("● ouvindo", "#3a9e6a")
            self._caption_main.setStyleSheet(
                "color: #ffffff; font-size: 22px; font-weight: 500;"
            )

    def _set_status(self, text: str, color: str):
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color}; font-size: 11px;")

    # ── Drag para mover a janela ───────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    # ── Resize: bg acompanha o tamanho da janela ───────────────────────────────

    def resizeEvent(self, event):
        self._bg.setGeometry(0, 0, self.width(), self.height())

    # ── Limpeza ao fechar ─────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._capture:
            self._capture.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        event.accept()
