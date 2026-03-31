"""
Detecta dispositivos de áudio para o Live Captions.

Windows: pyaudiowpatch expõe loopback devices nativamente — nenhuma
         configuração extra necessária. O formato paInt16 é usado na
         captura por ser universalmente suportado por drivers WASAPI.

macOS:   sounddevice + BlackHole.
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
        return f"{self.name} [{tag}, {self.native_sample_rate}Hz, {self.channels}ch]"


# ── API pública ────────────────────────────────────────────────────────────────

def detect_system_audio() -> Optional["AudioDevice"]:
    if platform.system() == "Windows":
        return _detect_windows_loopback()
    elif platform.system() == "Darwin":
        return _detect_macos_blackhole()
    return None


def detect_microphone() -> Optional["AudioDevice"]:
    try:
        import sounddevice as sd
        idx = sd.default.device[0]
        if idx < 0:
            return None
        dev = sd.query_devices(idx)
        ch = max(1, min(int(dev["max_input_channels"]), 2))
        return AudioDevice(
            index=idx,
            name=dev["name"],
            channels=ch,
            native_sample_rate=int(dev.get("default_samplerate", 48000)),
            mode=CaptureMode.MICROPHONE,
            is_loopback=False,
        )
    except Exception as e:
        logger.error(f"[Detector] Erro ao detectar microfone: {e}")
        return None


def list_system_devices() -> list["AudioDevice"]:
    if platform.system() == "Windows":
        return _list_windows_loopback_devices()
    elif platform.system() == "Darwin":
        return _list_macos_blackhole_devices()
    return []


def list_microphone_devices() -> list["AudioDevice"]:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return [
            AudioDevice(
                index=i,
                name=dev["name"],
                channels=max(1, min(int(dev["max_input_channels"]), 2)),
                native_sample_rate=int(dev.get("default_samplerate", 48000)),
                mode=CaptureMode.MICROPHONE,
                is_loopback=False,
            )
            for i, dev in enumerate(devices)
            if int(dev["max_input_channels"]) > 0
        ]
    except Exception:
        return []


# ── Windows ───────────────────────────────────────────────────────────────────

def _detect_windows_loopback() -> Optional["AudioDevice"]:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        logger.error("[Detector] pyaudiowpatch não instalado: pip install pyaudiowpatch")
        return None

    p = pyaudio.PyAudio()
    try:
        wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
        logger.info(f"[Detector] Saída padrão: '{default_out['name']}'")

        all_lb = list(p.get_loopback_device_info_generator())
        if not all_lb:
            logger.warning("[Detector] Nenhum loopback encontrado pelo pyaudiowpatch")
            return None

        logger.info(f"[Detector] {len(all_lb)} loopback(s) disponível(is):")
        for lb in all_lb:
            logger.info(
                f"  [{int(lb['index'])}] '{lb['name']}' "
                f"ch={int(lb['maxInputChannels'])} "
                f"rate={int(lb['defaultSampleRate'])}Hz"
            )

        # Prefere o loopback que corresponde à saída padrão
        for lb in all_lb:
            if default_out["name"] in lb["name"]:
                return _make_loopback_device(lb)

        # Fallback: primeiro disponível
        logger.warning(f"[Detector] Sem match — usando '{all_lb[0]['name']}'")
        return _make_loopback_device(all_lb[0])

    except Exception as e:
        logger.error(f"[Detector] Erro: {e}")
        return None
    finally:
        p.terminate()


def _make_loopback_device(lb: dict) -> "AudioDevice":
    """
    Cria AudioDevice a partir do dict retornado pelo pyaudiowpatch.
    Usa o número de canais exato reportado — NÃO capa.
    O capture.py lida com qualquer valor via mixagem.
    """
    raw_ch = int(lb["maxInputChannels"])
    # Garante mínimo 1 para não passar 0 ao PyAudio
    ch = max(1, raw_ch)
    return AudioDevice(
        index=int(lb["index"]),
        name=lb["name"],
        channels=ch,
        native_sample_rate=int(lb["defaultSampleRate"]),
        mode=CaptureMode.SYSTEM,
        is_loopback=True,
    )


def _list_windows_loopback_devices() -> list["AudioDevice"]:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return []
    p = pyaudio.PyAudio()
    result = []
    try:
        for lb in p.get_loopback_device_info_generator():
            result.append(_make_loopback_device(lb))
    except Exception as e:
        logger.error(f"[Detector] Erro ao listar loopbacks: {e}")
    finally:
        p.terminate()
    return result


# ── macOS ─────────────────────────────────────────────────────────────────────

def _detect_macos_blackhole() -> Optional["AudioDevice"]:
    try:
        import sounddevice as sd
        for i, dev in enumerate(sd.query_devices()):
            if "blackhole" in dev["name"].lower() and int(dev["max_input_channels"]) > 0:
                return AudioDevice(
                    index=i,
                    name=dev["name"],
                    channels=max(1, min(int(dev["max_input_channels"]), 2)),
                    native_sample_rate=int(dev.get("default_samplerate", 48000)),
                    mode=CaptureMode.SYSTEM,
                    is_loopback=False,
                )
    except Exception as e:
        logger.error(f"[Detector] Erro BlackHole: {e}")
    return None


def _list_macos_blackhole_devices() -> list["AudioDevice"]:
    try:
        import sounddevice as sd
        return [
            AudioDevice(
                index=i,
                name=dev["name"],
                channels=max(1, min(int(dev["max_input_channels"]), 2)),
                native_sample_rate=int(dev.get("default_samplerate", 48000)),
                mode=CaptureMode.SYSTEM,
                is_loopback=False,
            )
            for i, dev in enumerate(sd.query_devices())
            if int(dev["max_input_channels"]) > 0
        ]
    except Exception:
        return []