import logging

from fastapi import APIRouter, HTTPException

from models.schemas import TranslateRequest, TranslateResponse
from services.argos_service import argos_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/translate", response_model=TranslateResponse)
async def translate(request: TranslateRequest):
    """
    Traduz texto usando Argos Translate (offline).

    Entrada:
        text       — texto a ser traduzido
        sourceLang — idioma de origem (ISO 639-1)
        targetLang — idioma de destino (ISO 639-1)

    Saída:
        translated — texto traduzido
        sourceLang — idioma de origem
        targetLang — idioma de destino
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Campo 'text' não pode estar vazio")

    if request.sourceLang == request.targetLang:
        # Mesmos idiomas — retorna original sem chamar o modelo
        return TranslateResponse(
            translated=request.text,
            sourceLang=request.sourceLang,
            targetLang=request.targetLang,
        )

    try:
        translated = argos_service.translate(
            text=request.text,
            source_lang=request.sourceLang,
            target_lang=request.targetLang,
        )
        return TranslateResponse(
            translated=translated,
            sourceLang=request.sourceLang,
            targetLang=request.targetLang,
        )

    except Exception as e:
        logger.error(f"Erro na tradução: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro interno na tradução")
