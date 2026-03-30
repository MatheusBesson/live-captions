"""
Overlay de legendas — janela principal do app.

Características:
- Frameless e sempre visível sobre qualquer janela (Meet, YouTube etc.)
- Fundo semi-transparente arrastável pelo usuário
- Exibe legenda original (cinza) e traduzida (branca)
- Seletor de idioma alvo embutido
- Botão de pausa e configurações

CORREÇÕES aplicadas:
  - TranscribeWorker agora usa um slot Qt conectado via signal (process_chunk),
    garantindo que requests.post rode SEMPRE na thread do worker, nunca na thread
    de áudio. Antes o transcribe() era chamado direto da thread de áudio.
  - Fila de chunks com tamanho máximo 1: se o backend ainda está processando o
    chunk anterior, o novo simplesmente substitui (drop oldest). Isso evita
    acúmulo de requisições simultâneas e lag crescente de legendas.
  - _is_busy flag: impede que um segundo requests.post seja disparado enquanto
    o primeiro ainda não retornou.
  - config.py lido uma vez via import — API_TRANSCRIBE sempre atualizado.
"""

import queue
import threading

from PyQt6.QtCore import Qt, QPoint, QThread, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFrame,
)

import requests

from app.audio.capture import AudioCapture
from app.audio.device_detector import AudioDevice, CaptureMode, detect_microphone
from app.config import SUPPORTED_LANGUAGES, API_TRANSCRIBE


# ── Worker Thread ─────────────────────────────────────────────────────────────

class TranscribeWorker(QObject):
    """
    Recebe chunks de áudio via signal Qt e os envia ao backend.
    Roda inteiramente na sua própria QThread — nunca bloqueia a UI nem o áudio.

    Fila de tamanho 1 (substitui o chunk anterior se ainda não processado):
    mantém as legendas em tempo real sem acumular lag.
    """
    result_ready   = pyqtSignal(str, str)   # (original, translated)
    error_occurred = pyqtSignal(str)

    # Signal interno: a thread de áudio deposita o chunk aqui
    _chunk_received = pyqtSignal(str)

    def __init__(self, target_language: str):
        super().__init__()
        self.target_language = target_language
        self._is_busy = False
        # Fila de tamanho 1 — sempre processa o chunk mais recente
        self._pending: str | None = None
        self._lock = threading.Lock()
        # Conecta o signal interno ao slot de processamento (mesma thread)
        self._chunk_received.connect(self._process)

    def submit(self, audio_b64: str):
        """
        Chamado da thread de áudio via signal Qt (thread-safe).
        Deposita o chunk na fila e dispara processamento se não estiver ocupado.
        """
        with self._lock:
            self._pending = audio_b64   # substitui chunk anterior não processado
        if not self._is_busy:
            self._chunk_received.emit(audio_b64)

    @pyqtSlot(str)
    def _process(self, _audio_b64: str):
        """Executa na thread do worker — faz o POST ao backend."""
        with self._lock:
            audio_b64 = self._pending
            self._pending = None
            if audio_b64 is None:
                return

        self._is_busy = True
        try:
            payload = {
                "audio": audio_b64,
                "targetLanguage": self.target_language,
                "sampleRate": 16000,
            }
            response = requests.post(API_TRANSCRIBE, json=payload, timeout=10)
            response.raise_for_status()
            data       = response.json()
            original   = data.get("original",   "")
            translated = data.get("translated",  original)

            if original.strip():
                self.result_ready.emit(original, translated)

        except requests.exceptions.ConnectionError:
            self.error_occurred.emit("Backend offline")
        except requests.exceptions.Timeout:
            self.error_occurred.emit("Timeout — backend lento")
        except Exception as e:
            self.error_occurred.emit(f"Erro: {e}")
        finally:
            self._is_busy = False
            # Se chegou um novo chunk enquanto processávamos, dispara imediatamente
            with self._lock:
                if self._pending is not None:
                    self._chunk_received.emit(self._pending)


# ── Overlay Window ─────────────────────────────────────────────────────────────

class OverlayWindow(QWidget):
    # Signal para entregar chunk ao worker de forma thread-safe
    _audio_ready = pyqtSignal(str)

    def __init__(self, device: AudioDevice):
        super().__init__()
        self._device      = device
        self._drag_pos: QPoint | None = None
        self._is_paused   = False
        self._target_lang = "en"

        self._capture: AudioCapture | None = None
        self._worker:  TranscribeWorker | None = None
        self._thread:  QThread | None = None

        self._setup_window()
        self._setup_ui()
        self._setup_audio()

    # ── Janela ────────────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
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

        bg = QWidget(self, objectName="bg")
        bg.setGeometry(0, 0, self.width(), self.height())
        self._bg = bg

        outer = QVBoxLayout(bg)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(4)

        # ── Barra de controles ────────────────────────────────────────────────
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)

        self._status_label = QLabel("● ouvindo", objectName="status")
        self._status_label.setStyleSheet("color: #3a9e6a; font-size: 11px;")
        top_bar.addWidget(self._status_label)
        top_bar.addStretch()

        self._source_btn = QPushButton("🔊 sistema")
        self._source_btn.setToolTip("Alternar entre áudio do sistema e microfone")
        self._source_btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.06); border: 1px solid "
            "rgba(255,255,255,0.12); border-radius: 6px; color: #aaa; font-size: 11px; "
            "padding: 3px 10px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.12); color: #fff; }"
        )
        self._source_btn.clicked.connect(self._toggle_source)
        top_bar.addWidget(self._source_btn)

        lang_hint = QLabel("traduzir para:")
        lang_hint.setStyleSheet("color: #555; font-size: 11px;")
        top_bar.addWidget(lang_hint)

        self._lang_combo = QComboBox()
        for name, code in SUPPORTED_LANGUAGES.items():
            self._lang_combo.addItem(name, code)
        idx = list(SUPPORTED_LANGUAGES.values()).index("en")
        self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top_bar.addWidget(self._lang_combo)

        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setToolTip("Pausar / Retomar")
        self._pause_btn.clicked.connect(self._toggle_pause)
        top_bar.addWidget(self._pause_btn)

        close_btn = QPushButton("✕")
        close_btn.setToolTip("Fechar")
        close_btn.clicked.connect(self.close)
        top_bar.addWidget(close_btn)

        outer.addLayout(top_bar)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: rgba(255,255,255,0.06);")
        outer.addWidget(sep)

        # ── Área de legendas ──────────────────────────────────────────────────
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
        self._thread = QThread()
        self._worker = TranscribeWorker(target_language=self._target_lang)
        self._worker.moveToThread(self._thread)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)

        # Conecta o signal da overlay ao submit do worker (cross-thread seguro)
        self._audio_ready.connect(self._worker.submit)

        self._thread.start()
        self._start_capture(self._device)

    def _start_capture(self, device: AudioDevice):
        if self._capture and self._capture.is_running:
            self._capture.stop()

        mode_label = "sistema" if device.mode == CaptureMode.SYSTEM else "microfone"
        icon       = "🔊" if device.mode == CaptureMode.SYSTEM else "🎤"
        self._source_btn.setText(f"{icon} {mode_label}")

        self._capture = AudioCapture(device=device, on_chunk=self._on_audio_chunk)
        try:
            self._capture.start()
            self._set_status("● ouvindo", "#3a9e6a")
        except Exception as e:
            self._set_status("⚠ erro no áudio", "#e05a5a")
            self._caption_main.setText(f"Erro ao abrir dispositivo: {e}")

    def _toggle_source(self):
        if self._device.mode == CaptureMode.SYSTEM:
            mic = detect_microphone()
            if mic:
                self._device = mic
                self._start_capture(mic)
            else:
                self._caption_main.setText("Nenhum microfone encontrado.")
        else:
            from app.audio.device_detector import detect_system_audio
            sys_dev = detect_system_audio()
            if sys_dev:
                self._device = sys_dev
                self._start_capture(sys_dev)
            else:
                self._caption_main.setText("Dispositivo de sistema não encontrado.")

    def _on_audio_chunk(self, audio_b64: str):
        """
        Chamado pela thread de áudio (pyaudiowpatch callback).
        Emite signal Qt — entrega ao worker de forma thread-safe e retorna
        imediatamente, sem bloquear o callback de áudio.
        """
        if not self._is_paused:
            self._audio_ready.emit(audio_b64)

    # ── Slots de resultado ────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_result(self, original: str, translated: str):
        show_original = original.strip() != translated.strip()
        if show_original:
            self._caption_original.setText(original)
            self._caption_original.show()
        else:
            self._caption_original.hide()

        self._caption_main.setStyleSheet(
            "color: #ffffff; font-size: 22px; font-weight: 500; font-family: sans-serif;"
        )
        self._caption_main.setText(translated)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._caption_main.setStyleSheet(
            "color: #e05a5a; font-size: 14px; font-family: sans-serif;"
        )
        self._caption_main.setText(msg)

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

    # ── Drag ──────────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def resizeEvent(self, event):
        self._bg.setGeometry(0, 0, self.width(), self.height())

    # ── Limpeza ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._capture:
            self._capture.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        event.accept()