"""
Integração com faster-whisper para transcrição de áudio.

O modelo é carregado uma única vez na inicialização do FastAPI
e mantido em memória para evitar delay nas requisições seguintes.
"""

import base64
import io
import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

# faster-whisper é importado com lazy loading para não quebrar
# o servidor caso o modelo ainda não tenha sido baixado
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


class WhisperService:
    """
    Wrapper do faster-whisper.

    Modelo padrão: "small" (~244MB, boa velocidade/precisão para prototipagem)
    Para mais precisão use "medium" — mais lento, ~769MB.
    """

    def __init__(self, model_size: str = "small", device: str = "cpu"):
        self._model = None
        self._model_size = model_size
        self._device = device

    def load(self):
        """
        Carrega o modelo em memória.
        Chamado uma vez na inicialização do FastAPI (startup event).
        O download do modelo ocorre automaticamente na primeira execução (~244MB).
        """
        if not WHISPER_AVAILABLE:
            logger.warning("[WhisperService] faster-whisper indisponível — modo stub ativo")
            return

        logger.info(f"[WhisperService] Carregando modelo '{self._model_size}'...")
        start = time.time()
        self._model = WhisperModel(
            self._model_size,
            device=self._device,
            compute_type="int8",        # int8 reduz uso de memória sem perda significativa
        )
        elapsed = time.time() - start
        logger.info(f"[WhisperService] Modelo carregado em {elapsed:.1f}s")

    def transcribe(self, audio_b64: str, sample_rate: int = 16000) -> TranscriptionResult:
        """
        Transcreve áudio recebido em base64.

        O áudio deve estar em formato PCM float32, mono, 16kHz
        (exatamente como enviado pela captura do sounddevice).
        """
        if self._model is None:
            # Modo stub — retorna texto fictício para testes sem modelo
            logger.debug("[WhisperService] Stub: retornando transcrição fictícia")
            return TranscriptionResult(
                text="[modelo não carregado — instale faster-whisper]",
                language="pt",
                duration=3.0,
            )

        # Decodifica base64 → numpy array float32
        audio_bytes = base64.b64decode(audio_b64)
        audio_np = np.frombuffer(audio_bytes, dtype=np.float32)

        # Normaliza amplitude para evitar distorção
        if audio_np.max() > 1.0:
            audio_np = audio_np / audio_np.max()

        logger.debug(f"[WhisperService] Transcrevendo {len(audio_np)/sample_rate:.1f}s de áudio")

        segments, info = self._model.transcribe(
            audio_np,
            beam_size=5,
            language=None,          # None = detecção automática de idioma
            vad_filter=True,        # remove silêncio para economizar processamento
            vad_parameters=dict(
                min_silence_duration_ms=500,
            ),
        )

        # Consome o gerador de segments
        text_parts = [seg.text.strip() for seg in segments]
        full_text = " ".join(text_parts).strip()

        return TranscriptionResult(
            text=full_text,
            language=info.language,
            duration=info.duration,
        )


# Instância singleton — compartilhada pelos routers via injeção
whisper_service = WhisperService(model_size="small", device="cpu")
