import logging

from fastapi import APIRouter, HTTPException

from models.schemas import TranscribeRequest, TranscribeResponse
from services.whisper_service import whisper_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest):
    """
    Transcreve áudio em base64 usando Whisper.

    Entrada:
        audio      — áudio PCM float32 16kHz mono codificado em base64
        sampleRate — taxa de amostragem (padrão 16000)

    Saída:
        text     — texto transcrito
        language — código ISO 639-1 do idioma detectado ("pt", "en"...)
        duration — duração do áudio em segundos
    """
    if not request.audio:
        raise HTTPException(status_code=400, detail="Campo 'audio' obrigatório")

    try:
        result = whisper_service.transcribe(
            audio_b64=request.audio,
            sample_rate=request.sampleRate,
        )
        return TranscribeResponse(
            text=result.text,
            language=result.language,
            duration=result.duration,
        )

    except ValueError as e:
        logger.warning(f"Áudio inválido: {e}")
        raise HTTPException(status_code=422, detail=f"Áudio inválido: {e}")

    except Exception as e:
        logger.error(f"Erro na transcrição: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno na transcrição")
