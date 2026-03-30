import os
import platform

APP_NAME    = "Live Captions"
APP_VERSION = "0.1.0"

# ── Backend ───────────────────────────────────────────────────────────────────
# Fluxo: UI → Spring Boot :8080 → FastAPI :8001
#
# Spring Boot roda pelo IntelliJ, FastAPI pelo PyCharm.
# Para chamar FastAPI diretamente (sem Spring Boot):
#   set API_BASE_URL=http://localhost:8001   (Windows CMD)
#   export API_BASE_URL=http://localhost:8001 (PowerShell/bash)

API_BASE_URL   = os.getenv("API_BASE_URL", "http://localhost:8080")
API_TRANSCRIBE = f"{API_BASE_URL}/api/captions/transcribe"
API_TRANSLATE  = f"{API_BASE_URL}/api/captions/translate"

# ── Áudio ─────────────────────────────────────────────────────────────────────

WHISPER_SAMPLE_RATE = 16000   # Hz — não altere (Whisper espera exatamente 16kHz)
CHANNELS       = 1            # mono — stereo é mixado automaticamente na captura
CHUNK_DURATION = 3            # segundos por chunk enviado ao backend
BLOCKSIZE      = 1024         # frames por callback do driver de áudio

# ── Idiomas disponíveis no seletor da UI ──────────────────────────────────────

SUPPORTED_LANGUAGES = {
    "Português":  "pt",
    "English":    "en",
    "Español":    "es",
    "Français":   "fr",
    "Deutsch":    "de",
    "Italiano":   "it",
    "日本語":      "ja",
    "中文":        "zh",
}

PLATFORM = platform.system()   # "Windows" | "Darwin" | "Linux"

BLACKHOLE_URL  = "https://existential.audio/blackhole/"
BLACKHOLE_BREW = "brew install blackhole-2ch"