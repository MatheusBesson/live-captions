"""
Captura contínua de áudio — sistema (loopback) ou microfone.

Windows sistema  → pyaudiowpatch (WASAPI loopback nativo)
Windows microfone→ sounddevice (dispositivo de entrada padrão)
macOS sistema    → sounddevice + BlackHole
macOS microfone  → sounddevice

Resample automático: captura na taxa nativa do hardware e converte
para 16000Hz antes de enviar ao backend.

CORREÇÕES aplicadas:
  - Cap defensivo de canais (evita PaErrorCode -9998).
  - Verificação de RMS local: chunks de silêncio puro não são enviados ao
    backend, economizando CPU do Whisper e evitando logs de "VAD removed".
  - Log de amplitude por chunk para facilitar diagnóstico.
  - Código morto removido. self._pa.terminate() garantido no caminho de falha.
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

from config import CHUNK_DURATION, WHISPER_SAMPLE_RATE
from audio.device_detector import AudioDevice, CaptureMode

logger = logging.getLogger(__name__)

BLOCKSIZE = 1024   # frames por callback

# Mesmo threshold do whisper_service.py — chunks abaixo disto são silêncio puro
# e não precisam ser enviados ao backend.
_MIN_RMS = 5e-4


class AudioCapture:
    def __init__(self, device: AudioDevice, on_chunk: Callable[[str], None]):
        self._device       = device
        self._on_chunk     = on_chunk
        self._capture_rate = device.native_sample_rate
        self._target_rate  = WHISPER_SAMPLE_RATE

        _g               = gcd(self._target_rate, self._capture_rate)
        self._up         = self._target_rate  // _g
        self._down       = self._capture_rate // _g
        self._needs_resample = (self._capture_rate != self._target_rate)

        self._chunk_samples = self._capture_rate * CHUNK_DURATION

        self._queue:   queue.Queue             = queue.Queue()
        self._buffer:  list[np.ndarray]        = []
        self._running: bool                    = False
        self._thread:  threading.Thread | None = None
        self._actual_channels: int             = self._device.channels

        # Handles de backend
        self._pa        = None
        self._pa_stream = None
        self._sd_stream = None

        # Contadores para log periódico
        self._chunks_sent    = 0
        self._chunks_silence = 0

        logger.info(
            f"[AudioCapture] '{device.name}' | "
            f"loopback={device.is_loopback} | "
            f"channels={device.channels} | "
            f"{self._capture_rate}Hz → {self._target_rate}Hz"
        )

    # ── Controle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._buffer.clear()
        self._chunks_sent    = 0
        self._chunks_silence = 0

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
        logger.info("[AudioCapture] Captura iniciada")

    def stop(self):
        self._running = False
        if self._pa_stream:
            try:
                self._pa_stream.stop_stream()
                self._pa_stream.close()
            except Exception:
                pass
            self._pa_stream = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        if self._sd_stream:
            try:
                self._sd_stream.stop()
                self._sd_stream.close()
            except Exception:
                pass
            self._sd_stream = None
        logger.info(
            f"[AudioCapture] Encerrado — "
            f"chunks enviados={self._chunks_sent}, "
            f"silêncios ignorados={self._chunks_silence}"
        )

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

        # Cap defensivo — WASAPI reporta valores brutos que o driver recusa
        reported = max(1, min(self._device.channels, 2))
        candidates: list[int] = [reported]
        for fallback in (2, 1):
            if fallback not in candidates:
                candidates.append(fallback)

        last_error: Exception | None = None

        for ch in candidates:
            try:
                logger.info(f"[AudioCapture] Tentando loopback com {ch} canal(is)...")
                _ch = ch

                def _pa_callback(
                    in_data, frame_count, time_info, status,
                    _channels=_ch,
                ):
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
                logger.info(f"[AudioCapture] Loopback WASAPI OK — {ch} canal(is)")
                return

            except Exception as e:
                last_error = e
                logger.warning(f"[AudioCapture] Falha com {ch} canal(is): {e}")

        try:
            self._pa.terminate()
        except Exception:
            pass
        self._pa = None
        raise RuntimeError(
            f"Não foi possível abrir '{self._device.name}' "
            f"(tentativas: {candidates}). Último erro: {last_error}"
        )

    # ── sounddevice — microfone ou BlackHole (macOS) ──────────────────────────

    def _start_sounddevice(self):
        import sounddevice as sd

        def _sd_callback(indata, frames, time, status):
            if status:
                logger.warning(f"[AudioCapture] sounddevice: {status}")
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
        logger.info(
            f"[AudioCapture] sounddevice OK — "
            f"device={self._device.index} ch={self._device.channels} "
            f"rate={self._capture_rate}Hz"
        )

    # ── Loop de processamento ─────────────────────────────────────────────────

    def _process_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            block, ch = item
            block = np.asarray(block, dtype=np.float32).flatten()

            # Mixagem stereo → mono
            if ch > 1 and len(block) % ch == 0:
                block = block.reshape(-1, ch).mean(axis=1)

            self._buffer.append(block)
            total = sum(b.shape[0] for b in self._buffer)

            if total < self._chunk_samples:
                continue

            # Chunk completo
            audio = np.concatenate(self._buffer)[:self._chunk_samples]
            self._buffer = []

            # Resample para 16 kHz se necessário
            if self._needs_resample:
                audio = resample_poly(audio, self._up, self._down).astype(np.float32)

            # Normalização de amplitude (só se necessário — não distorcer sinal OK)
            peak = float(np.abs(audio).max())
            if peak > 1.0:
                audio = (audio / peak).astype(np.float32)

            # Verificação de silêncio local — evita envio desnecessário ao backend
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < _MIN_RMS:
                self._chunks_silence += 1
                if self._chunks_silence % 10 == 1:
                    logger.debug(
                        f"[AudioCapture] Silêncio (RMS={rms:.2e}) — "
                        f"chunk não enviado [{self._chunks_silence}x consecutivos]"
                    )
                continue

            # Há sinal — loga amplitude e envia
            self._chunks_silence = 0
            self._chunks_sent += 1
            logger.debug(
                f"[AudioCapture] Chunk #{self._chunks_sent} enviado — "
                f"RMS={rms:.2e} peak={peak:.4f}"
            )

            audio_b64 = base64.b64encode(audio.tobytes()).decode("utf-8")
            try:
                self._on_chunk(audio_b64)
            except Exception as e:
                logger.error(f"[AudioCapture] Erro no callback on_chunk: {e}")