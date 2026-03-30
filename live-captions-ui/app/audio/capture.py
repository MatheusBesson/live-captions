"""
Captura contínua de áudio do dispositivo de sistema selecionado.

Roda em thread separada para não bloquear a UI.
A cada CHUNK_DURATION segundos, chama on_chunk(audio_b64).

Resample automático:
  O dispositivo pode capturar em qualquer frequência (48000Hz, 44100Hz, 96000Hz...).
  Este módulo detecta a frequência nativa, captura nela e faz resample para
  16000Hz (exigido pelo Whisper) antes de enviar ao backend.
  O usuário não precisa configurar nada.
"""

import base64
import queue
import threading
import logging
from math import gcd
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

import sounddevice as sd

from app.config import BLOCKSIZE, CHUNK_DURATION, WHISPER_SAMPLE_RATE
from app.audio.device_detector import AudioDevice

logger = logging.getLogger(__name__)


class AudioCapture:
    def __init__(self, device: AudioDevice, on_chunk: Callable[[str], None]):
        """
        device    : AudioDevice com index e native_sample_rate detectados
        on_chunk  : callback chamado com o áudio em base64 (PCM float32, 16kHz)
                    já pronto para enviar ao backend
        """
        self._device = device
        self._on_chunk = on_chunk

        # Taxa nativa do hardware (ex: 48000Hz)
        self._capture_rate = device.native_sample_rate
        # Taxa alvo do Whisper (16000Hz)
        self._target_rate = WHISPER_SAMPLE_RATE

        # Fator de resample calculado pelo MDC para máxima precisão numérica
        _g = gcd(self._target_rate, self._capture_rate)
        self._resample_up   = self._target_rate  // _g
        self._resample_down = self._capture_rate // _g
        self._needs_resample = (self._capture_rate != self._target_rate)

        # Samples na taxa nativa que equivalem a CHUNK_DURATION segundos
        self._chunk_samples_native = self._capture_rate * CHUNK_DURATION

        self._queue: queue.Queue = queue.Queue()
        self._buffer: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._running = False
        self._thread: threading.Thread | None = None

        logger.info(
            f"[AudioCapture] {device.name} | "
            f"nativo: {self._capture_rate}Hz → Whisper: {self._target_rate}Hz | "
            f"resample: {'sim ({}/{}x)'.format(self._resample_up, self._resample_down) if self._needs_resample else 'não necessário'}"
        )

    # ── Controle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._buffer.clear()

        self._stream = sd.InputStream(
            device=self._device.index,
            samplerate=self._capture_rate,   # captura na frequência NATIVA do hardware
            channels=self._device.channels,
            dtype="float32",
            blocksize=BLOCKSIZE,
            callback=self._sd_callback,
        )
        self._stream.start()

        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Internals ─────────────────────────────────────────────────────────────

    def _sd_callback(self, indata: np.ndarray, frames: int, time, status):
        if status:
            logger.warning(f"[AudioCapture] status sounddevice: {status}")
        self._queue.put(indata.copy())

    def _process_loop(self):
        while self._running:
            try:
                block = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # Mixagem para mono se o dispositivo capturou em stereo
            if block.ndim > 1 and block.shape[1] > 1:
                block = block.mean(axis=1)
            else:
                block = block.flatten()

            self._buffer.append(block)
            total = sum(b.shape[0] for b in self._buffer)

            if total < self._chunk_samples_native:
                continue

            # Chunk completo — processa e zera o buffer
            audio_native = np.concatenate(self._buffer)[:self._chunk_samples_native]
            self._buffer = []

            # ── Resample: frequência nativa → 16000Hz ─────────────────────────
            if self._needs_resample:
                audio_16k = resample_poly(
                    audio_native,
                    up=self._resample_up,
                    down=self._resample_down,
                ).astype(np.float32)
            else:
                audio_16k = audio_native.astype(np.float32)

            # Normaliza amplitude para [-1.0, 1.0] — range esperado pelo Whisper
            peak = np.abs(audio_16k).max()
            if peak > 1.0:
                audio_16k /= peak

            print(f"[Audio] max: {audio_16k.max()} | min: {audio_16k.min()} | peak: {peak}")

            # Encode base64 e dispara callback
            audio_b64 = base64.b64encode(audio_16k.tobytes()).decode("utf-8")
            try:
                self._on_chunk(audio_b64)
            except Exception as e:
                logger.error(f"[AudioCapture] Erro no callback: {e}")