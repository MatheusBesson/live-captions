"""
FastAPI — microsserviço de IA para o Live Captions.

Responsabilidades únicas:
  POST /transcribe → Whisper (transcrição de áudio)
  POST /translate  → Argos Translate (tradução offline)

Intencionalmente sem lógica de negócio — apenas expõe os modelos de IA.
Toda orquestração e decisão de fluxo fica no Spring Boot.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from routers import transcribe, translate
from services.argos_service import argos_service
from services.whisper_service import whisper_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Carrega os modelos de IA na inicialização do servidor.

    Os modelos ficam em memória durante toda a execução para evitar
    o delay de carregamento a cada requisição.
    """
    logger.info("Iniciando Live Captions FastAPI...")

    # Carrega Whisper (baixa o modelo na primeira execução ~244MB)
    whisper_service.load()

    # Verifica e instala pacotes de idioma do Argos (primeira execução ~100MB/par)
    argos_service.load()

    logger.info("FastAPI pronto — aguardando requisições na porta 8001")
    yield

    # Cleanup ao desligar (libera memória do modelo se necessário)
    logger.info("Encerrando FastAPI...")


app = FastAPI(
    title="Live Captions AI Service",
    description="Microsserviço de transcrição e tradução para o Live Captions",
    version="0.1.0",
    lifespan=lifespan,
)

# Registra os routers
app.include_router(transcribe.router, tags=["Transcrição"])
app.include_router(translate.router, tags=["Tradução"])


@app.get("/health")
async def health():
    """Health check — usado pelo Spring Boot para verificar disponibilidade."""
    return {
        "status": "ok",
        "service": "live-captions-fastapi",
        "whisper": "loaded" if whisper_service._model else "stub",
        "argos": "loaded" if argos_service._initialized else "stub",
    }
