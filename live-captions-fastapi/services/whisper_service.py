"""
Integração com faster-whisper para transcrição de áudio.

O modelo é carregado uma única vez na inicialização do FastAPI
e mantido em memória para evitar delay nas requisições seguintes.

CORREÇÕES aplicadas:
  - VAD menos agressivo: threshold reduzido para não descartar áudio de sistema
    (loopback WASAPI tende a ter amplitude mais baixa que microfone).
  - Log de diagnóstico de amplitude: avisa quando o sinal é suspeito de silêncio
    genuíno vs. sinal presente mas descartado pelo VAD.
  - vad_filter=False como fallback quando todos os segmentos são removidos:
    re-transcreve sem VAD para confirmar se há conteúdo.
  - min_speech_duration_ms reduzido para capturar trechos curtos.
"""

import base64
import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning("faster-whisper não instalado. Usando modo stub.")


@dataclass
class TranscriptionResult:
    text: str
    language: str
    duration: float


# Amplitude RMS mínima para considerar que há sinal de áudio real.
# Abaixo disto o chunk é silêncio genuíno e não vale enviar ao Whisper.
# WASAPI loopback em silêncio gera ~1e-7; fala real fica acima de 1e-3.
_MIN_RMS = 5e-4


class WhisperService:
    """
    Wrapper do faster-whisper.

    Modelo padrão: "small" (~244MB, boa velocidade/precisão para prototipagem).
    Para mais precisão use "medium" — mais lento, ~769MB.
    """

    def __init__(self, model_size: str = "small", device: str = "cpu"):
        self._model = None
        self._model_size = model_size
        self._device = device

    def load(self):
        if not WHISPER_AVAILABLE:
            logger.warning("[WhisperService] faster-whisper indisponível — modo stub ativo")
            return

        logger.info(f"[WhisperService] Carregando modelo '{self._model_size}'...")
        start = time.time()
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type="int8",
        )
        elapsed = time.time() - start
        logger.info(f"[WhisperService] Modelo carregado em {elapsed:.1f}s")

    def transcribe(self, audio_b64: str, sample_rate: int = 16000) -> TranscriptionResult:
        """
        Transcreve áudio recebido em base64 (PCM float32, mono, 16kHz).

        Pipeline:
          1. Decodifica base64 → numpy float32
          2. Verifica RMS — se silêncio genuíno, retorna "" imediatamente
          3. Transcreve com VAD ligado
          4. Se VAD removeu tudo mas havia sinal, re-transcreve sem VAD
        """
        if self._model is None:
            return TranscriptionResult(
                text="[modelo não carregado — instale faster-whisper]",
                language="pt",
                duration=3.0,
            )

        # 1. Decodifica
        audio_bytes = base64.b64decode(audio_b64)
        audio_np = np.frombuffer(audio_bytes, dtype=np.float32).copy()

        if len(audio_np) == 0:
            logger.warning("[WhisperService] Chunk vazio recebido")
            return TranscriptionResult(text="", language="pt", duration=0.0)

        # Normaliza amplitude se necessário (clipping)
        peak = float(np.abs(audio_np).max())
        if peak > 1.0:
            audio_np = audio_np / peak

        # 2. Verificação de silêncio por RMS
        rms = float(np.sqrt(np.mean(audio_np ** 2)))
        duration_s = len(audio_np) / sample_rate
        logger.debug(f"[WhisperService] Chunk {duration_s:.1f}s | RMS={rms:.2e} | peak={peak:.4f}")

        if rms < _MIN_RMS:
            logger.debug(f"[WhisperService] Silêncio genuíno (RMS={rms:.2e} < {_MIN_RMS:.2e}) — ignorando")
            return TranscriptionResult(text="", language="pt", duration=duration_s)

        # 3. Transcrição com VAD
        result = self._run_transcribe(audio_np, use_vad=True)

        # 4. Fallback sem VAD se havia sinal mas VAD removeu tudo
        if not result.text and rms >= _MIN_RMS * 10:
            logger.info(
                f"[WhisperService] VAD removeu áudio com sinal (RMS={rms:.2e}) — "
                f"re-transcrevendo sem VAD"
            )
            result = self._run_transcribe(audio_np, use_vad=False)

        if result.text:
            logger.info(f"[WhisperService] ✓ '{result.text[:80]}'  [{result.language}]")
        else:
            logger.debug(f"[WhisperService] Chunk sem fala detectada (RMS={rms:.2e})")

        return result

    def _run_transcribe(self, audio_np: np.ndarray, use_vad: bool) -> TranscriptionResult:
        """Executa a transcrição com ou sem filtro VAD."""
        kwargs = dict(
            beam_size=5,
            language=None,          # detecção automática
            vad_filter=use_vad,
        )

        if use_vad:
            kwargs["vad_parameters"] = dict(
                # Padrão do faster-whisper é 0.5 — reduzimos para não
                # descartar fala real de baixa amplitude (áudio de sistema).
                threshold=0.3,
                min_speech_duration_ms=100,   # captura trechos curtos
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            )

        segments, info = self._model.transcribe(audio_np, **kwargs)

        text_parts = [seg.text.strip() for seg in segments]
        full_text = " ".join(text_parts).strip()

        return TranscriptionResult(
            text=full_text,
            language=info.language,
            duration=info.duration,
        )


# Instância singleton
whisper_service = WhisperService(model_size="small", device="cpu")