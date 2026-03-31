"""
Captura contínua de áudio — sistema (loopback) ou microfone.

Windows loopback → pyaudiowpatch, API bloqueante (stream.read)
  Segue exatamente o padrão dos exemplos oficiais da biblioteca.
  Evita todos os problemas de callback/channel/format.

Windows microfone / macOS → sounddevice

Resample automático: taxa nativa do hardware → 16000Hz (Whisper).
"""

import base64
import platform
import threading
import logging
from math import gcd
from typing import Callable

import numpy as np
from scipy.signal import resample_poly

from config import CHUNK_DURATION, WHISPER_SAMPLE_RATE
from audio.device_detector import AudioDevice, CaptureMode

logger = logging.getLogger(__name__)

BLOCKSIZE = 512
_MIN_RMS  = 5e-4


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

        self._running = False
        self._thread: threading.Thread | None = None

        self._pa        = None
        self._pa_stream = None
        self._sd_stream = None

        logger.info(
            f"[AudioCapture] '{device.name}' | loopback={device.is_loopback} | "
            f"ch={device.channels} | {self._capture_rate}Hz → {self._target_rate}Hz"
        )

    # ── Controle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True

        use_loopback = (
            platform.system() == "Windows"
            and self._device.is_loopback
        )

        if use_loopback:
            self._thread = threading.Thread(
                target=self._loopback_loop, daemon=True
            )
        else:
            self._thread = threading.Thread(
                target=self._sounddevice_loop, daemon=True
            )

        self._thread.start()
        logger.info("[AudioCapture] Captura iniciada")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Loop pyaudiowpatch (bloqueante) ───────────────────────────────────────

    def _loopback_loop(self):
        """
        Lê o loopback usando a API bloqueante do pyaudiowpatch.
        Este é o padrão usado nos exemplos oficiais da biblioteca —
        evita todos os problemas de formato/canais do callback API.
        """
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            logger.error("[AudioCapture] pyaudiowpatch não instalado")
            return

        p = pyaudio.PyAudio()
        self._pa = p

        # Busca info do dispositivo diretamente pelo pyaudio
        # para garantir que usamos exatamente o que ele reporta
        try:
            dev_info = p.get_device_info_by_index(self._device.index)
        except Exception as e:
            logger.error(f"[AudioCapture] Dispositivo não encontrado: {e}")
            p.terminate()
            return

        ch   = int(dev_info["maxInputChannels"])
        rate = int(dev_info["defaultSampleRate"])

        logger.info(
            f"[AudioCapture] Abrindo loopback: idx={self._device.index} "
            f"ch={ch} rate={rate}Hz format=paInt16"
        )

        try:
            stream = p.open(
                format=pyaudio.paInt16,
                channels=ch,
                rate=rate,
                frames_per_buffer=BLOCKSIZE,
                input=True,
                input_device_index=self._device.index,
            )
        except Exception as e:
            logger.error(f"[AudioCapture] Falha ao abrir loopback: {e}")
            p.terminate()
            self._pa = None
            return

        self._pa_stream = stream
        logger.info("[AudioCapture] Loopback WASAPI aberto com sucesso")

        buffer: list[np.ndarray] = []

        while self._running:
            try:
                raw = stream.read(BLOCKSIZE, exception_on_overflow=False)
            except Exception as e:
                if self._running:
                    logger.warning(f"[AudioCapture] Erro ao ler stream: {e}")
                break

            # int16 → float32 normalizado [-1, 1]
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            # Mixagem para mono se stereo
            if ch > 1 and len(pcm) % ch == 0:
                pcm = pcm.reshape(-1, ch).mean(axis=1)

            buffer.append(pcm)
            total = sum(b.shape[0] for b in buffer)

            if total < self._chunk_samples:
                continue

            audio = np.concatenate(buffer)[:self._chunk_samples]
            buffer = []

            self._send(audio, rate)

        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass
        self._pa        = None
        self._pa_stream = None
        logger.info("[AudioCapture] Loop loopback encerrado")

    # ── Loop sounddevice (microfone / BlackHole) ──────────────────────────────

    def _sounddevice_loop(self):
        import sounddevice as sd
        import queue as _queue

        q: _queue.Queue = _queue.Queue()
        ch   = self._device.channels
        rate = self._capture_rate

        def _cb(indata, frames, time, status):
            if status:
                logger.warning(f"[AudioCapture] sounddevice: {status}")
            q.put(indata.copy())

        try:
            stream = sd.InputStream(
                device=self._device.index,
                samplerate=rate,
                channels=ch,
                dtype="float32",
                blocksize=BLOCKSIZE,
                callback=_cb,
            )
        except Exception as e:
            logger.error(f"[AudioCapture] Falha ao abrir microfone: {e}")
            return

        self._sd_stream = stream
        stream.start()
        logger.info(f"[AudioCapture] sounddevice OK ({ch}ch, {rate}Hz)")

        buffer: list[np.ndarray] = []

        while self._running:
            try:
                block = q.get(timeout=0.5)
            except Exception:
                continue

            block = np.asarray(block, dtype=np.float32).flatten()
            if ch > 1 and len(block) % ch == 0:
                block = block.reshape(-1, ch).mean(axis=1)

            buffer.append(block)
            total = sum(b.shape[0] for b in buffer)

            if total < self._chunk_samples:
                continue

            audio = np.concatenate(buffer)[:self._chunk_samples]
            buffer = []

            self._send(audio, rate)

        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        self._sd_stream = None
        logger.info("[AudioCapture] Loop sounddevice encerrado")

    # ── Pipeline de processamento comum ──────────────────────────────────────

    def _send(self, audio: np.ndarray, source_rate: int):
        """Resample → normaliza → filtra silêncio → envia ao backend."""

        # Resample para 16kHz se necessário
        if source_rate != self._target_rate:
            _g   = gcd(self._target_rate, source_rate)
            up   = self._target_rate  // _g
            down = source_rate // _g
            audio = resample_poly(audio, up, down).astype(np.float32)

        # Normaliza amplitude
        peak = float(np.abs(audio).max())
        if peak > 1.0:
            audio = (audio / peak).astype(np.float32)

        # Silêncio — não envia
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < _MIN_RMS:
            logger.debug(f"[AudioCapture] Silêncio (RMS={rms:.2e}) — ignorado")
            return

        logger.debug(f"[AudioCapture] Enviando chunk RMS={rms:.2e}")
        audio_b64 = base64.b64encode(audio.tobytes()).decode("utf-8")
        try:
            self._on_chunk(audio_b64)
        except Exception as e:
            logger.error(f"[AudioCapture] Erro no callback: {e}")