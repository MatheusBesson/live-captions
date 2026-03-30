"""
Tela de onboarding exibida quando nenhum dispositivo de áudio do sistema é detectado.

Windows → orienta habilitar o Stereo Mix
macOS   → orienta instalar o BlackHole
Ambos   → permite selecionar manualmente qualquer dispositivo de entrada
"""

import platform
import subprocess
import sys
import webbrowser

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from audio.device_detector import AudioDevice, list_system_devices, list_microphone_devices
from config import BLACKHOLE_BREW, BLACKHOLE_URL


class OnboardingWindow(QWidget):
    """
    Janela de configuração inicial.
    Emite device_selected(AudioDevice) quando o usuário confirma um dispositivo.
    """

    device_selected = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self._system = platform.system()
        self._devices: list[AudioDevice] = []
        self._confirm_btn: QPushButton | None = None   # inicializa antes de _setup_ui
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle("Live Captions — Configuração")
        self.setMinimumWidth(520)
        self.setStyleSheet("""
            QWidget { background: #1a1a1a; color: #e0e0e0; font-family: sans-serif; }
            QFrame#card {
                background: #242424;
                border: 1px solid #333;
                border-radius: 12px;
                padding: 8px;
            }
            QPushButton {
                background: #2d5a8e;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-size: 13px;
            }
            QPushButton:hover  { background: #3a6fa8; }
            QPushButton:pressed { background: #1e3d5c; }
            QPushButton#secondary {
                background: #2a2a2a;
                border: 1px solid #444;
                color: #ccc;
            }
            QPushButton#secondary:hover { background: #333; }
            QComboBox {
                background: #2a2a2a;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                color: #e0e0e0;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #2a2a2a;
                border: 1px solid #444;
                selection-background-color: #2d5a8e;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(16)

        # Título
        title = QLabel("Configuração de áudio")
        title.setFont(QFont("sans-serif", 16, QFont.Weight.Medium))
        title.setStyleSheet("color: #ffffff;")
        root.addWidget(title)

        # Instruções específicas por SO
        card = QFrame(objectName="card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(10)

        if self._system == "Windows":
            self._build_windows_instructions(card_layout)
        elif self._system == "Darwin":
            self._build_macos_instructions(card_layout)
        else:
            card_layout.addWidget(QLabel(
                "Nenhum dispositivo de áudio do sistema detectado automaticamente.\n"
                "Selecione manualmente um dispositivo abaixo."
            ))

        root.addWidget(card)

        # Separador
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        root.addWidget(sep)

        # Seleção manual
        manual_label = QLabel("Selecione o dispositivo de saída de áudio (fones/alto-falantes):")
        manual_label.setStyleSheet("color: #aaa; font-size: 12px;")
        root.addWidget(manual_label)

        self._combo = QComboBox()
        root.addWidget(self._combo)

        # Botões — criados ANTES de _populate_combo para evitar AttributeError
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        refresh_btn = QPushButton("Atualizar lista", objectName="secondary")
        refresh_btn.clicked.connect(self._refresh_devices)
        btn_row.addWidget(refresh_btn)

        btn_row.addStretch()

        self._confirm_btn = QPushButton("Confirmar e iniciar")
        self._confirm_btn.clicked.connect(self._confirm)
        btn_row.addWidget(self._confirm_btn)

        root.addLayout(btn_row)

        # Popula o combo agora que _confirm_btn já existe
        self._devices = list_system_devices()
        self._populate_combo()

    def _build_windows_instructions(self, layout: QVBoxLayout):
        layout.addWidget(self._info_label(
            "Nenhum dispositivo de áudio do sistema foi detectado."
        ))
        layout.addWidget(self._info_label(
            "Verifique se o pyaudiowpatch está instalado no ambiente da UI:"
        ))

        cmd_label = QLabel("  > pip install pyaudiowpatch")
        cmd_label.setStyleSheet(
            "font-family: monospace; background: #1a1a1a; color: #7dd3a8;"
            "padding: 8px 12px; border-radius: 6px; font-size: 12px;"
        )
        layout.addWidget(cmd_label)

        layout.addWidget(self._info_label(
            "Após instalar, feche o app e abra novamente — o dispositivo será "
            "detectado automaticamente. Ou selecione manualmente abaixo."
        ))

    def _build_macos_instructions(self, layout: QVBoxLayout):
        layout.addWidget(self._info_label(
            "O macOS não permite capturar o áudio do sistema nativamente."
        ))
        layout.addWidget(self._info_label(
            "Instale o BlackHole, um driver virtual gratuito e open source:"
        ))

        brew_label = QLabel(f"  $ {BLACKHOLE_BREW}")
        brew_label.setStyleSheet(
            "font-family: monospace; background: #1a1a1a; color: #7dd3a8;"
            "padding: 8px 12px; border-radius: 6px; font-size: 12px;"
        )
        layout.addWidget(brew_label)

        btn_row = QHBoxLayout()
        download_btn = QPushButton("Baixar BlackHole (site oficial)")
        download_btn.setObjectName("secondary")
        download_btn.clicked.connect(lambda: webbrowser.open(BLACKHOLE_URL))
        btn_row.addWidget(download_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(self._info_label(
            "Após instalar, clique em 'Atualizar lista' abaixo."
        ))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _info_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color: #ccc; font-size: 13px;")
        return lbl

    def _populate_combo(self):
        self._combo.clear()
        if self._devices:
            for dev in self._devices:
                self._combo.addItem(f"{dev.name}  ({dev.native_sample_rate}Hz)", dev)
            self._combo.setEnabled(True)
            self._confirm_btn.setEnabled(True)
        else:
            self._combo.addItem("Nenhum dispositivo encontrado")
            self._combo.setEnabled(False)
            self._confirm_btn.setEnabled(False)

    def _refresh_devices(self):
        self._devices = list_system_devices()
        self._populate_combo()

    def _confirm(self):
        device: AudioDevice = self._combo.currentData()
        if device:
            self.device_selected.emit(device)
            self.close()