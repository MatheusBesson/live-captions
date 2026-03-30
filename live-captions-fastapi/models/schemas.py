from pydantic import BaseModel, Field


# ── Transcrição ───────────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    audio: str = Field(..., description="Áudio em base64 (PCM float32, mono)")
    sampleRate: int = Field(16000, description="Taxa de amostragem em Hz")


class TranscribeResponse(BaseModel):
    text: str
    language: str           # código ISO 639-1 detectado pelo Whisper
    duration: float = 0.0   # duração do áudio em segundos


# ── Tradução ──────────────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str = Field(..., description="Texto a ser traduzido")
    sourceLang: str = Field(..., description="Idioma de origem (ISO 639-1)")
    targetLang: str = Field(..., description="Idioma de destino (ISO 639-1)")


class TranslateResponse(BaseModel):
    translated: str
    sourceLang: str
    targetLang: str


# ── Erros ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
