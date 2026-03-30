"""
Captura contínua de áudio — sistema (loopback) ou microfone.

Windows sistema  → pyaudiowpatch (WASAPI loopback nativo)
Windows microfone→ sounddevice (dispositivo de entrada padrão)
macOS sistema    → sounddevice + BlackHole
macOS microfone  → sounddevice

Resample automático: captura na taxa nativa do hardware e converte
para 16000Hz antes de enviar ao Whisper.
"""

import base64
import platform
import queue
import threading
import logging
from math import gcd
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

from app.config import CHUNK_DURATION, WHISPER_SAMPLE_RATE
from app.audio.device_detector import AudioDevice, CaptureMode

logger = logging.getLogger(__name__)

BLOCKSIZE = 1024   # frames por callback


class AudioCapture:
    def __init__(self, device: AudioDevice, on_chunk: Callable[[str], None]):
        self._device      = device
        self._on_chunk    = on_chunk
        self._capture_rate = device.native_sample_rate
        self._target_rate  = WHISPER_SAMPLE_RATE

        _g          = gcd(self._target_rate, self._capture_rate)
        self._up    = self._target_rate  // _g
        self._down  = self._capture_rate // _g
        self._needs_resample = (self._capture_rate != self._target_rate)

        self._chunk_samples = self._capture_rate * CHUNK_DURATION

        self._queue:   queue.Queue              = queue.Queue()
        self._buffer:  list[np.ndarray]          = []
        self._running: bool                      = False
        self._thread:  threading.Thread | None   = None
        self._actual_channels: int               = self._device.channels

        # Handles específicos por backend
        self._pa_stream = None   # pyaudiowpatch
        self._sd_stream = None   # sounddevice

        logger.info(
            f"[AudioCapture] '{device.name}' | "
            f"loopback={device.is_loopback} | "
            f"{self._capture_rate}Hz → {self._target_rate}Hz"
        )

    # ── Controle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._buffer.clear()

        use_pyaudio = (
            platform.system() == "Windows"
            and self._device.mode == CaptureMode.SYSTEM
            and self._device.is_loopback
        )

        if use_pyaudio:
            self._start_pyaudio_loopback()
        else:
            self._start_sounddevice()

        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._pa_stream:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
                self._pa.terminate()
            except Exception:
                pass
            self._pa_stream = None
        if self._sd_stream:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None

    @property
    def is_running(self) -> bool:
        return self._running

    # ── pyaudiowpatch — WASAPI loopback (Windows sistema) ────────────────────

    def _start_pyaudio_loopback(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            raise RuntimeError(
                "pyaudiowpatch não instalado.\n"
                "Execute: pip install pyaudiowpatch"
            )

        self._pa = pyaudio.PyAudio()

        # Ordem de tentativa: valor reportado → 2 → 1
        reported = self._device.channels
        candidates = []
        if reported > 0:
            candidates.append(reported)
        for fallback in (2, 1):
            if fallback not in candidates:
                candidates.append(fallback)

        last_error = None
        for ch in candidates:
            try:
                logger.info(f"[AudioCapture] Tentando abrir loopback com {ch} canal(is)...")

                # Captura o valor de ch no closure
                _ch = ch

                def _pa_callback(in_data, frame_count, time_info, status,
                                  _channels=_ch):
                    if self._running and in_data:
                        audio = np.frombuffer(in_data, dtype=np.float32).copy()
                        self._queue.put((audio, _channels))
                    return (None, pyaudio.paContinue)

                self._pa_stream = self._pa.open(
                    format=pyaudio.paFloat32,
                    channels=ch,
                    rate=self._capture_rate,
                    frames_per_buffer=BLOCKSIZE,
                    input=True,
                    input_device_index=self._device.index,
                    stream_callback=_pa_callback,
                )
                self._pa_stream.start_stream()
                self._actual_channels = ch
                logger.info(f"[AudioCapture] Loopback iniciado com {ch} canal(is)")
                return

            except Exception as e:
                last_error = e
                logger.warning(f"[AudioCapture] Falha com {ch} canal(is): {e}")

        raise RuntimeError(
            f"Não foi possível abrir o dispositivo de loopback "
            f"'{self._device.name}': {last_error}"
        )
        self._pa_stream.start_stream()
        logger.info("[AudioCapture] pyaudiowpatch loopback iniciado")

    # ── sounddevice — microfone ou BlackHole (macOS) ──────────────────────────

    def _start_sounddevice(self):
        import sounddevice as sd

        def _sd_callback(indata, frames, time, status):
            if status:
                logger.warning(f"[AudioCapture] {status}")
            self._queue.put((indata.copy(), self._device.channels))

        self._sd_stream = sd.InputStream(
            device=self._device.index,
            samplerate=self._capture_rate,
            channels=self._device.channels,
            dtype="float32",
            blocksize=BLOCKSIZE,
            callback=_sd_callback,
        )
        self._sd_stream.start()
        self._actual_channels = self._device.channels
        logger.info("[AudioCapture] sounddevice stream iniciado")

    # ── Loop de processamento comum ───────────────────────────────────────────

    def _process_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Desempacota (audio_array, channel_count)
            block, ch = item
            block = np.asarray(block, dtype=np.float32).flatten()

            # Mixagem para mono usando o número real de canais
            if ch > 1 and len(block) % ch == 0:
                block = block.reshape(-1, ch).mean(axis=1)

            self._buffer.append(block)
            total = sum(b.shape[0] for b in self._buffer)

            if total < self._chunk_samples:
                continue

            # Chunk completo — processa e reseta buffer
            audio = np.concatenate(self._buffer)[:self._chunk_samples]
            self._buffer = []

            # Resample para 16000Hz
            if self._needs_resample:
                audio = resample_poly(audio, self._up, self._down).astype(np.float32)

            # Normaliza amplitude para [-1, 1]
            peak = np.abs(audio).max()
            if peak > 1.0:
                audio /= peak

            audio_b64 = base64.b64encode(audio.tobytes()).decode("utf-8")
            try:
                self._on_chunk(audio_b64)
            except Exception as e:
                logger.error(f"[AudioCapture] Erro no callback: {e}")