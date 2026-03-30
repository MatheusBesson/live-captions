"""
Detecta automaticamente o dispositivo de captura de áudio do sistema.

Windows → WASAPI loopback / Stereo Mix
macOS   → BlackHole (driver virtual gratuito)
"""

import platform
from dataclasses import dataclass
from typing import Optional

import sounddevice as sd


@dataclass
class AudioDevice:
    index: int
    name: str
    channels: int
    native_sample_rate: int = 48000     # taxa real do hardware — detectada automaticamente

    def __str__(self):
        return f"{self.name} (canais: {self.channels}, {self.native_sample_rate}Hz)"


def _get_native_sample_rate(device_index: int) -> int:
    """
    Lê a taxa de amostragem nativa reportada pelo driver do dispositivo.
    A maioria dos equipamentos modernos usa 48000Hz, mas pode ser 44100 ou 96000.
    Fallback para 48000 se não conseguir detectar.
    """
    try:
        info = sd.query_devices(device_index)
        rate = int(info.get("default_samplerate", 48000))
        return rate if rate > 0 else 48000
    except Exception:
        return 48000


def detect_system_audio() -> Optional[AudioDevice]:
    """
    Tenta encontrar automaticamente o dispositivo de áudio do sistema.
    Retorna None se não encontrar — a UI deve mostrar o onboarding.
    """
    system = platform.system()
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return None

    if system == "Windows":
        return _detect_windows(devices, hostapis)
    elif system == "Darwin":
        return _detect_macos(devices)
    return None


def list_input_devices() -> list[AudioDevice]:
    """Lista todos os dispositivos com canais de entrada — usado na tela de seleção manual."""
    try:
        devices = sd.query_devices()
        return [
            AudioDevice(
                index=i,
                name=dev["name"],
                channels=min(dev["max_input_channels"], 2),
                native_sample_rate=_get_native_sample_rate(i),
            )
            for i, dev in enumerate(devices)
            if dev["max_input_channels"] > 0
        ]
    except Exception:
        return []


# ── Helpers por plataforma ────────────────────────────────────────────────────
#PEGA AUDIO MICROFONE
''' def _detect_windows(devices, hostapis) -> Optional[AudioDevice]: 
    """
    Procura pelo WASAPI loopback ou Stereo Mix.
    O WASAPI loopback captura o áudio que sai pelos alto-falantes sem nenhuma
    configuração extra — é o método preferido.
    """
    wasapi_idx = next(
        (i for i, api in enumerate(hostapis) if "WASAPI" in api["name"]),
        None,
    )

    if wasapi_idx is not None:
        # Palavras-chave que identificam dispositivos de loopback no Windows
        loopback_keywords = ["loopback", "stereo mix", "what u hear", "wave out mix"]
        for i, dev in enumerate(devices):
            if dev["hostapi"] != wasapi_idx:
                continue
            if dev["max_input_channels"] <= 0:
                continue

            name_lower = dev["name"].lower()

            if any(kw in name_lower for kw in loopback_keywords):
                return AudioDevice(
                    index=i,
                    name=dev["name"],
                    channels=min(dev["max_input_channels"], 2),
                    native_sample_rate=_get_native_sample_rate(i),
                )

    # Fallback: qualquer dispositivo de entrada WASAPI disponível
    if wasapi_idx is not None:
        for i, dev in enumerate(devices):
            if dev["hostapi"] == wasapi_idx and dev["max_input_channels"] > 0:
                return AudioDevice(
                    index=i,
                    name=dev["name"],
                    channels=min(dev["max_input_channels"], 2),
                    native_sample_rate=_get_native_sample_rate(i),
                )

    return None '''

def _detect_windows(devices, hostapis) -> Optional[AudioDevice]:
    wasapi_idx = next(
        (i for i, api in enumerate(hostapis) if "WASAPI" in api["name"]),
        None,
    )

    if wasapi_idx is None:
        return None

    # 1. Primeiro tenta Stereo Mix (mais fácil)
    loopback_keywords = ["stereo mix", "what u hear", "wave out mix"]

    for i, dev in enumerate(devices):
        if dev["hostapi"] != wasapi_idx:
            continue

        name_lower = dev["name"].lower()

        if any(kw in name_lower for kw in loopback_keywords) and dev["max_input_channels"] > 0:
            return AudioDevice(
                index=i,
                name=dev["name"],
                channels=min(dev["max_input_channels"], 2),
                native_sample_rate=_get_native_sample_rate(i),
            )

    # 2. FALLBACK: usar OUTPUT como loopback
    for i, dev in enumerate(devices):
        if dev["hostapi"] != wasapi_idx:
            continue

        # 👇 pega device de saída
        if dev["max_output_channels"] > 0:
            return AudioDevice(
                index=i,
                name=f"{dev['name']} (loopback)",
                channels=2,
                native_sample_rate=_get_native_sample_rate(i),
            )

    return None


def _detect_macos(devices) -> Optional[AudioDevice]:
    """
    Procura pelo BlackHole — driver virtual open source que
    captura o áudio do sistema no macOS.
    """
    for i, dev in enumerate(devices):
        if "blackhole" in dev["name"].lower() and dev["max_input_channels"] > 0:
            return AudioDevice(
                index=i,
                name=dev["name"],
                channels=min(dev["max_input_channels"], 2),
                native_sample_rate=_get_native_sample_rate(i),
            )
    return None