import os
import platform

APP_NAME = "Live Captions"
APP_VERSION = "0.1.0"

# Backend — só mudar esta linha para produção
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
API_TRANSCRIBE = f"{API_BASE_URL}/api/captions/transcribe"

# ── Áudio ─────────────────────────────────────────────────────────────────────

# Taxa de amostragem que o Whisper espera receber — NÃO altere este valor.
# O app captura na frequência nativa do dispositivo (48000Hz, 44100Hz, etc.)
# e faz resample automático para cá antes de enviar ao backend.
WHISPER_SAMPLE_RATE = 16000

CHANNELS = 1              # mono (mixagem feita automaticamente se o dispositivo for stereo)
CHUNK_DURATION = 3        # segundos por chunk enviado ao backend
BLOCKSIZE = 1024          # frames por callback do sounddevice

# ── Idiomas ───────────────────────────────────────────────────────────────────

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

BLACKHOLE_URL = "https://existential.audio/blackhole/"
BLACKHOLE_BREW = "brew install blackhole-2ch"