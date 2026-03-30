"""
Live Captions — ponto de entrada.

Fluxo de inicialização:
1. Tenta detectar automaticamente o dispositivo de áudio do sistema
2a. Se encontrar → abre o overlay direto
2b. Se não encontrar → abre o onboarding para guiar o usuário
3. Onboarding emite device_selected → abre o overlay com o dispositivo escolhido
"""

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

from audio.device_detector import detect_system_audio, AudioDevice
from ui.onboarding import OnboardingWindow
from ui.overlay import OverlayWindow
from config import APP_NAME, APP_VERSION


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    # Permite que a app continue rodando mesmo sem janelas visíveis
    # (o overlay pode ser minimizado no futuro via tray icon)
    app.setQuitOnLastWindowClosed(True)

    device = detect_system_audio()

    if device:
        print(f"[Init] Dispositivo detectado: {device}")
        _open_overlay(app, device)
    else:
        print("[Init] Nenhum dispositivo detectado — abrindo onboarding")
        _open_onboarding(app)

    sys.exit(app.exec())


def _open_overlay(app: QApplication, device: AudioDevice):
    overlay = OverlayWindow(device)
    # Posiciona no canto inferior central da tela
    screen = app.primaryScreen().geometry()
    overlay.move(
        (screen.width() - overlay.width()) // 2,
        screen.height() - overlay.height() - 80,
    )
    overlay.show()
    # Mantém referência para não ser coletado pelo GC
    app._overlay = overlay


def _open_onboarding(app: QApplication):
    onboarding = OnboardingWindow()

    def on_device_selected(device: AudioDevice):
        print(f"[Onboarding] Dispositivo selecionado: {device}")
        _open_overlay(app, device)

    onboarding.device_selected.connect(on_device_selected)
    onboarding.show()
    app._onboarding = onboarding


if __name__ == "__main__":
    main()
