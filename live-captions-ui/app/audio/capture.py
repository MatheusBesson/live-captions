"""
Captura contínua de áudio — sistema (loopback) ou microfone.

Windows loopback → pyaudiowpatch com formato paInt16
  paInt16 é aceito por TODOS os drivers WASAPI, ao contrário de paFloat32
  que alguns drivers rejeitam (PaErrorCode -9998).
  O áudio é convertido para float32 no callback antes de entrar na fila.

Windows microfone / macOS → sounddevice (paFloat32 nativo)

Resample automático: taxa nativa do hardware → 16000Hz (Whisper).
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

BLOCKSIZE = 512    # frames por callback — menor = menos latência

# Threshold de silêncio: chunks com RMS abaixo disto não são enviados ao backend
_MIN_RMS = 5e-4


class AudioCapture:
    def __init__(self, device: AudioDevice, on_chunk: Callable[[str], None]):
        self._device       = device
        self._on_chunk     = on_chunk
        self._capture_rate = device.native_sample_rate
        self._target_rate  = WHISPER_SAMPLE_RATE

        _g           = gcd(self._target_rate, self._capture_rate)
        self._up     = self._target_rate  // _g
        self._down   = self._capture_rate // _g
        self._needs_resample = (self._capture_rate != self._target_rate)

        self._chunk_samples = self._capture_rate * CHUNK_DURATION

        self._queue:   queue.Queue             = queue.Queue()
        self._buffer:  list[np.ndarray]        = []
        self._running: bool                    = False
        self._thread:  threading.Thread | None = None

        self._pa        = None
        self._pa_stream = None
        self._sd_stream = None

        self._chunks_sent    = 0
        self._chunks_silence = 0

        logger.info(
            f"[AudioCapture] '{device.name}' | loopback={device.is_loopback} | "
            f"ch={device.channels} | {self._capture_rate}Hz → {self._target_rate}Hz"
        )

    # ── Controle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._buffer.clear()

        use_loopback = (
            platform.system() == "Windows"
            and self._device.is_loopback
            and self._device.mode == CaptureMode.SYSTEM
        )

        if use_loopback:
            self._start_pyaudio_loopback()
        else:
            self._start_sounddevice()

        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("[AudioCapture] Captura iniciada")

    def stop(self):
        self._running = False
        for attr in ("_pa_stream", "_sd_stream"):
            obj = getattr(self, attr, None)
            if obj:
                try:
                    obj.stop_stream() if hasattr(obj, "stop_stream") else obj.stop()
                    obj.close()
                except Exception:
                    pass
                setattr(self, attr, None)
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        logger.info(
            f"[AudioCapture] Encerrado — enviados={self._chunks_sent} "
            f"silêncios={self._chunks_silence}"
        )

    @property
    def is_running(self) -> bool:
        return self._running

    # ── pyaudiowpatch — WASAPI loopback ───────────────────────────────────────

    def _start_pyaudio_loopback(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            raise RuntimeError("pyaudiowpatch não instalado: pip install pyaudiowpatch")

        self._pa = pyaudio.PyAudio()
        ch = self._device.channels   # valor reportado pelo loopback device

        # paInt16 é o formato mais compatível com drivers WASAPI.
        # Evita o PaErrorCode -9998 que paFloat32 causa em alguns drivers.
        def _callback(in_data, frame_count, time_info, status, _ch=ch):
            if self._running and in_data:
                # Converte int16 → float32 normalizado [-1, 1]
                pcm = np.frombuffer(in_data, dtype=np.int16).astype(np.float32)
                pcm /= 32768.0
                self._queue.put((pcm, _ch))
            return (None, pyaudio.paContinue)

        try:
            self._pa_stream = self._pa.open(
                format=pyaudio.paInt16,    # ← formato universal para WASAPI
                channels=ch,
                rate=self._capture_rate,
                frames_per_buffer=BLOCKSIZE,
                input=True,
                input_device_index=self._device.index,
                stream_callback=_callback,
            )
            self._pa_stream.start_stream()
            logger.info(f"[AudioCapture] Loopback WASAPI OK (paInt16, {ch}ch, {self._capture_rate}Hz)")

        except Exception as e:
            logger.error(f"[AudioCapture] Falha ao abrir loopback: {e}")
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
            raise RuntimeError(
                f"Não foi possível abrir o dispositivo de loopback '{self._device.name}'.\n"
                f"Detalhe: {e}"
            )

    # ── sounddevice — microfone ou BlackHole (macOS) ──────────────────────────

    def _start_sounddevice(self):
        import sounddevice as sd

        ch = self._device.channels

        def _callback(indata, frames, time, status):
            if status:
                logger.warning(f"[AudioCapture] sounddevice: {status}")
            self._queue.put((indata.copy(), ch))

        self._sd_stream = sd.InputStream(
            device=self._device.index,
            samplerate=self._capture_rate,
            channels=ch,
            dtype="float32",
            blocksize=BLOCKSIZE,
            callback=_callback,
        )
        self._sd_stream.start()
        logger.info(f"[AudioCapture] sounddevice OK ({ch}ch, {self._capture_rate}Hz)")

    # ── Loop de processamento ─────────────────────────────────────────────────

    def _process_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            block, ch = item
            block = np.asarray(block, dtype=np.float32).flatten()

            # Mixagem para mono
            if ch > 1 and len(block) % ch == 0:
                block = block.reshape(-1, ch).mean(axis=1)

            self._buffer.append(block)
            total = sum(b.shape[0] for b in self._buffer)

            if total < self._chunk_samples:
                continue

            # Chunk completo
            audio = np.concatenate(self._buffer)[:self._chunk_samples]
            self._buffer = []

            # Resample para 16kHz
            if self._needs_resample:
                audio = resample_poly(audio, self._up, self._down).astype(np.float32)

            # Normaliza amplitude
            peak = float(np.abs(audio).max())
            if peak > 1.0:
                audio = (audio / peak).astype(np.float32)

            # Ignora silêncio
            rms = float(np.sqrt(np.mean(audio ** 2)))
            if rms < _MIN_RMS:
                self._chunks_silence += 1
                logger.debug(f"[AudioCapture] Silêncio RMS={rms:.2e} — não enviado")
                continue

            self._chunks_sent += 1
            self._chunks_silence = 0
            logger.debug(
                f"[AudioCapture] Chunk #{self._chunks_sent} | "
                f"RMS={rms:.2e} peak={peak:.3f}"
            )

            audio_b64 = base64.b64encode(audio.tobytes()).decode("utf-8")
            try:
                self._on_chunk(audio_b64)
            except Exception as e:
                logger.error(f"[AudioCapture] Erro no callback: {e}")