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

from app.audio.device_detector import AudioDevice, list_input_devices
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
        self._devices: list[AudioDevice] = list_input_devices()
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
        manual_label = QLabel("Ou selecione um dispositivo manualmente:")
        manual_label.setStyleSheet("color: #aaa; font-size: 12px;")
        root.addWidget(manual_label)

        self._combo = QComboBox()
        if self._devices:
            for dev in self._devices:
                self._combo.addItem(dev.name, dev)
        else:
            self._combo.addItem("Nenhum dispositivo encontrado")
            self._combo.setEnabled(False)
        root.addWidget(self._combo)

        # Botões
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        refresh_btn = QPushButton("Atualizar lista", objectName="secondary")
        refresh_btn.clicked.connect(self._refresh_devices)
        btn_row.addWidget(refresh_btn)

        btn_row.addStretch()

        confirm_btn = QPushButton("Confirmar e iniciar")
        confirm_btn.clicked.connect(self._confirm)
        confirm_btn.setEnabled(bool(self._devices))
        self._confirm_btn = confirm_btn
        btn_row.addWidget(confirm_btn)

        root.addLayout(btn_row)

    def _build_windows_instructions(self, layout: QVBoxLayout):
        layout.addWidget(self._info_label(
            "O dispositivo WASAPI Loopback não foi detectado automaticamente."
        ))
        layout.addWidget(self._info_label(
            "Para capturar o áudio do sistema no Windows, habilite o Stereo Mix:"
        ))

        steps = [
            "1. Clique com o botão direito no ícone de som na barra de tarefas",
            "2. Abra 'Configurações de som' → 'Mais configurações de som'",
            "3. Vá na aba 'Gravação'",
            "4. Clique com o botão direito em uma área vazia → 'Mostrar dispositivos desativados'",
            "5. Habilite o 'Stereo Mix' e clique em OK",
            "6. Clique em 'Atualizar lista' abaixo",
        ]
        for step in steps:
            lbl = QLabel(step)
            lbl.setStyleSheet("color: #bbb; font-size: 12px; padding-left: 8px;")
            layout.addWidget(lbl)

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

    def _refresh_devices(self):
        self._devices = list_input_devices()
        self._combo.clear()
        if self._devices:
            for dev in self._devices:
                self._combo.addItem(dev.name, dev)
            self._combo.setEnabled(True)
            self._confirm_btn.setEnabled(True)
        else:
            self._combo.addItem("Nenhum dispositivo encontrado")
            self._combo.setEnabled(False)
            self._confirm_btn.setEnabled(False)

    def _confirm(self):
        device: AudioDevice = self._combo.currentData()
        if device:
            self.device_selected.emit(device)
            self.close()
