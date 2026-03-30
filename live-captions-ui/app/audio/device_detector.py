"""
Detecta dispositivos de áudio para o Live Captions.

Windows: usa pyaudiowpatch para WASAPI loopback — biblioteca criada
         especificamente para capturar áudio do sistema no Windows.
         Detecta automaticamente o dispositivo de saída padrão (fones/alto-falantes).

macOS:   usa sounddevice + BlackHole (driver virtual gratuito).

Dois modos:
  SYSTEM     → áudio do sistema (YouTube, Meet, qualquer app)
  MICROPHONE → microfone (feature futura — detectado mas não usado por padrão)

CORREÇÕES aplicadas:
  - Cap de canais: WASAPI loopback reporta valores brutos (0, 18, 32, …) que
    o driver não aceita ao abrir o stream. Normalizado para max(1, min(ch, 2)).
  - Log diagnóstico: todos os loopbacks disponíveis são logados na inicialização
    para facilitar troubleshooting.
  - Fallback robusto: quando nenhum loopback tem nome correspondente à saída
    padrão, usa o primeiro disponível sem silenciar o erro.
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


def _safe_channels(raw: int, max_ch: int = 2) -> int:
    """
    Normaliza o número de canais reportado pelo hardware.

    WASAPI loopback pode reportar 0 (dispositivo silencioso/desconectado)
    ou valores altos (18, 32) que o driver recusa ao abrir o InputStream.
    Garantimos sempre 1 ≤ channels ≤ max_ch.
    """
    return max(1, min(int(raw), max_ch))


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
            channels=_safe_channels(dev["max_input_channels"]),
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
                channels=_safe_channels(dev["max_input_channels"]),
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

    Correção: _safe_channels() garante que channels nunca seja 0 nem > 2,
    evitando o PaErrorCode -9998 (Invalid number of channels) ao abrir o stream.
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
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out_idx = wasapi_info["defaultOutputDevice"]
        default_out     = p.get_device_info_by_index(default_out_idx)

        logger.info(f"[Detector] Saída padrão do sistema: '{default_out['name']}'")

        # Log diagnóstico — lista todos os loopbacks antes de escolher
        all_loopbacks = list(p.get_loopback_device_info_generator())
        if not all_loopbacks:
            logger.warning("[Detector] Nenhum dispositivo de loopback encontrado pelo pyaudiowpatch.")
            logger.warning(
                "[Detector] Verifique se o áudio do sistema está ativo e se "
                "pyaudiowpatch está instalado corretamente."
            )
            return None

        logger.info(f"[Detector] {len(all_loopbacks)} loopback(s) disponível(is):")
        for lb in all_loopbacks:
            raw_ch = int(lb["maxInputChannels"])
            safe_ch = _safe_channels(raw_ch)
            logger.info(
                f"  [{int(lb['index'])}] '{lb['name']}' "
                f"| canais brutos={raw_ch} → usará {safe_ch} "
                f"| rate={int(lb['defaultSampleRate'])}Hz"
            )

        # Tenta corresponder ao dispositivo de saída padrão
        for lb in all_loopbacks:
            if default_out["name"] in lb["name"]:
                logger.info(f"[Detector] Loopback selecionado (match): '{lb['name']}'")
                return AudioDevice(
                    index=int(lb["index"]),
                    name=lb["name"],
                    channels=_safe_channels(lb["maxInputChannels"]),
                    native_sample_rate=int(lb["defaultSampleRate"]),
                    mode=CaptureMode.SYSTEM,
                    is_loopback=True,
                )

        # Fallback: primeiro loopback disponível
        lb = all_loopbacks[0]
        logger.warning(
            f"[Detector] Nenhum loopback corresponde à saída padrão. "
            f"Usando fallback: '{lb['name']}'"
        )
        return AudioDevice(
            index=int(lb["index"]),
            name=lb["name"],
            channels=_safe_channels(lb["maxInputChannels"]),
            native_sample_rate=int(lb["defaultSampleRate"]),
            mode=CaptureMode.SYSTEM,
            is_loopback=True,
        )

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
        for lb in p.get_loopback_device_info_generator():
            result.append(AudioDevice(
                index=int(lb["index"]),
                name=lb["name"],
                channels=_safe_channels(lb["maxInputChannels"]),
                native_sample_rate=int(lb["defaultSampleRate"]),
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
                    channels=_safe_channels(dev["max_input_channels"]),
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
                channels=_safe_channels(dev["max_input_channels"]),
                native_sample_rate=int(dev.get("default_samplerate", 48000)),
                mode=CaptureMode.SYSTEM,
                is_loopback=False,
            )
            for i, dev in enumerate(devices)
            if int(dev["max_input_channels"]) > 0
        ]
    except Exception:
        return []