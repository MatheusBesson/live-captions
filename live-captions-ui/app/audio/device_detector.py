"""
Detecta dispositivos de áudio para o Live Captions.

Windows: usa pyaudiowpatch para WASAPI loopback — biblioteca criada
         especificamente para capturar áudio do sistema no Windows.
         Detecta automaticamente o dispositivo de saída padrão (fones/alto-falantes).

macOS:   usa sounddevice + BlackHole (driver virtual gratuito).

Dois modos:
  SYSTEM     → áudio do sistema (YouTube, Meet, qualquer app)
  MICROPHONE → microfone (feature futura — detectado mas não usado por padrão)
"""

import logging
import platform
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


class CaptureMode(Enum):
    SYSTEM     = auto()
    MICROPHONE = auto()


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    native_sample_rate: int = 48000
    mode: CaptureMode = CaptureMode.SYSTEM
    is_loopback: bool = False

    def __str__(self):
        tag = "sistema" if self.mode == CaptureMode.SYSTEM else "microfone"
        return f"{self.name} [{tag}, {self.native_sample_rate}Hz]"


# ── API pública ────────────────────────────────────────────────────────────────

def detect_system_audio() -> Optional[AudioDevice]:
    """Retorna o melhor dispositivo para capturar o áudio do sistema."""
    system = platform.system()
    if system == "Windows":
        return _detect_windows_loopback()
    elif system == "Darwin":
        return _detect_macos_blackhole()
    logger.warning("Plataforma sem suporte a captura de sistema")
    return None


def detect_microphone() -> Optional[AudioDevice]:
    """Retorna o microfone padrão do sistema."""
    try:
        import sounddevice as sd
        default_idx = sd.default.device[0]
        if default_idx < 0:
            return None
        dev = sd.query_devices(default_idx)
        return AudioDevice(
            index=default_idx,
            name=dev["name"],
            channels=min(int(dev["max_input_channels"]), 2),
            native_sample_rate=int(dev.get("default_samplerate", 48000)),
            mode=CaptureMode.MICROPHONE,
            is_loopback=False,
        )
    except Exception as e:
        logger.error(f"Erro ao detectar microfone: {e}")
        return None


def list_system_devices() -> list[AudioDevice]:
    """Lista dispositivos disponíveis para captura do sistema (seleção manual)."""
    system = platform.system()
    if system == "Windows":
        return _list_windows_loopback_devices()
    elif system == "Darwin":
        return _list_macos_blackhole_devices()
    return []


def list_microphone_devices() -> list[AudioDevice]:
    """Lista todos os microfones disponíveis."""
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            AudioDevice(
                index=i,
                name=dev["name"],
                channels=min(int(dev["max_input_channels"]), 2),
                native_sample_rate=int(dev.get("default_samplerate", 48000)),
                mode=CaptureMode.MICROPHONE,
                is_loopback=False,
            )
            for i, dev in enumerate(devices)
            if int(dev["max_input_channels"]) > 0
        ]
    except Exception:
        return []


# ── Windows — pyaudiowpatch ───────────────────────────────────────────────────

def _detect_windows_loopback() -> Optional[AudioDevice]:
    """
    Usa pyaudiowpatch para encontrar o dispositivo de loopback
    correspondente à saída padrão do sistema (fones, alto-falantes).

    pyaudiowpatch expõe dispositivos de loopback como entradas virtuais —
    não é necessário nenhuma configuração extra no Windows.
    """
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        logger.error(
            "pyaudiowpatch não instalado. "
            "Execute: pip install pyaudiowpatch"
        )
        return None

    p = pyaudio.PyAudio()
    try:
        # Informações da API WASAPI
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out_idx = wasapi_info["defaultOutputDevice"]
        default_out     = p.get_device_info_by_index(default_out_idx)

        logger.info(f"[Detector] Saída padrão: {default_out['name']}")

        # pyaudiowpatch já expõe dispositivos de loopback separados
        # Procura o loopback que corresponde à saída padrão
        for loopback in p.get_loopback_device_info_generator():
            if default_out["name"] in loopback["name"]:
                logger.info(f"[Detector] Loopback encontrado: {loopback['name']}")
                return AudioDevice(
                    index=int(loopback["index"]),
                    name=loopback["name"],
                    channels=int(loopback["maxInputChannels"]),   # valor exato — não capar
                    native_sample_rate=int(loopback["defaultSampleRate"]),
                    mode=CaptureMode.SYSTEM,
                    is_loopback=True,
                )

        # Fallback: primeiro loopback disponível
        for loopback in p.get_loopback_device_info_generator():
            logger.info(f"[Detector] Usando primeiro loopback: {loopback['name']}")
            return AudioDevice(
                index=int(loopback["index"]),
                name=loopback["name"],
                channels=int(loopback["maxInputChannels"]),   # valor exato — não capar
                native_sample_rate=int(loopback["defaultSampleRate"]),
                mode=CaptureMode.SYSTEM,
                is_loopback=True,
            )

        logger.warning("[Detector] Nenhum dispositivo de loopback encontrado")
        return None

    except Exception as e:
        logger.error(f"[Detector] Erro ao detectar loopback: {e}")
        return None
    finally:
        p.terminate()


def _list_windows_loopback_devices() -> list[AudioDevice]:
    """Lista todos os dispositivos de loopback disponíveis (para seleção manual)."""
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []

    p = pyaudio.PyAudio()
    result = []
    try:
        for loopback in p.get_loopback_device_info_generator():
            result.append(AudioDevice(
                index=int(loopback["index"]),
                name=loopback["name"],
                channels=int(loopback["maxInputChannels"]),   # valor exato
                native_sample_rate=int(loopback["defaultSampleRate"]),
                mode=CaptureMode.SYSTEM,
                is_loopback=True,
            ))
    except Exception as e:
        logger.error(f"[Detector] Erro ao listar loopbacks: {e}")
    finally:
        p.terminate()
    return result


# ── macOS — BlackHole ─────────────────────────────────────────────────────────

def _detect_macos_blackhole() -> Optional[AudioDevice]:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if "blackhole" in dev["name"].lower() and int(dev["max_input_channels"]) > 0:
                return AudioDevice(
                    index=i,
                    name=dev["name"],
                    channels=min(int(dev["max_input_channels"]), 2),
                    native_sample_rate=int(dev.get("default_samplerate", 48000)),
                    mode=CaptureMode.SYSTEM,
                    is_loopback=False,
                )
    except Exception as e:
        logger.error(f"[Detector] Erro ao detectar BlackHole: {e}")
    return None


def _list_macos_blackhole_devices() -> list[AudioDevice]:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            AudioDevice(
                index=i,
                name=dev["name"],
                channels=min(int(dev["max_input_channels"]), 2),
                native_sample_rate=int(dev.get("default_samplerate", 48000)),
                mode=CaptureMode.SYSTEM,
                is_loopback=False,
            )
            for i, dev in enumerate(devices)
            if int(dev["max_input_channels"]) > 0
        ]
    except Exception:
        return []