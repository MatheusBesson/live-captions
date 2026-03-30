#!/usr/bin/env python3
"""
start.py — inicia todos os serviços do Live Captions de uma vez.

Ordem de inicialização:
  1. FastAPI   (porta 8001) — modelos de IA precisam estar prontos primeiro
  2. Spring Boot (porta 8080) — espera o FastAPI responder antes de subir
  3. UI PyQt6  — espera o Spring Boot responder antes de abrir

Uso:
  python start.py            # inicia tudo
  python start.py --no-ui    # inicia só os backends (útil para debug)
"""

import argparse
import subprocess
import sys
import time
import os
import signal
from pathlib import Path

import requests

# ── Configurações ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent

FASTAPI_DIR  = ROOT / "live-captions-fastapi"
SPRING_JAR   = ROOT / "live-captions-backend" / "target" / "live-captions-backend-0.1.0.jar"
UI_DIR       = ROOT / "live-captions-ui"

FASTAPI_URL  = "http://localhost:8001/health"
SPRING_URL   = "http://localhost:8080/api/captions/health"

STARTUP_TIMEOUT = 60    # segundos máximos para cada serviço subir
POLL_INTERVAL   = 2     # segundos entre cada verificação de health

processes: list[subprocess.Popen] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"\033[36m[start]\033[0m {msg}", flush=True)

def log_ok(msg: str):
    print(f"\033[32m[  ok ]\033[0m {msg}", flush=True)

def log_err(msg: str):
    print(f"\033[31m[erro ]\033[0m {msg}", flush=True)


def wait_for_service(url: str, name: str, timeout: int = STARTUP_TIMEOUT) -> bool:
    """Aguarda o serviço responder no health check antes de continuar."""
    log(f"Aguardando {name} em {url}...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                log_ok(f"{name} está pronto")
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(POLL_INTERVAL)
    log_err(f"{name} não respondeu em {timeout}s")
    return False


def shutdown(signum=None, frame=None):
    """Para todos os processos ao receber CTRL+C ou SIGTERM."""
    log("Encerrando serviços...")
    for p in reversed(processes):
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    log("Todos os serviços encerrados.")
    sys.exit(0)


# ── Inicialização ─────────────────────────────────────────────────────────────

def start_fastapi() -> subprocess.Popen:
    log("Iniciando FastAPI (porta 8001)...")
    venv_python = FASTAPI_DIR / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    p = subprocess.Popen(
        [python, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"],
        cwd=str(FASTAPI_DIR),
    )
    processes.append(p)
    return p

'''
def start_spring() -> subprocess.Popen:
    if not SPRING_JAR.exists():
        log_err(f"JAR não encontrado em {SPRING_JAR}")
        log_err("Execute primeiro: cd live-captions-backend && mvn package -q")
        shutdown()

    log("Iniciando Spring Boot (porta 8080)...")
    p = subprocess.Popen(["java", "-jar", str(SPRING_JAR)])
    processes.append(p)
    return p '''



def start_ui() -> subprocess.Popen:
    log("Iniciando UI PyQt6...")
    venv_python = UI_DIR / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    p = subprocess.Popen(
        [python, "app/main.py"],
        cwd=str(UI_DIR),
    )
    processes.append(p)
    return p


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Live Captions — startup")
    parser.add_argument("--no-ui", action="store_true", help="Sobe apenas os backends")
    args = parser.parse_args()

    # Registra handlers para encerramento limpo
    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log("=== Live Captions — iniciando ===")

    # 1. FastAPI
    start_fastapi()
    if not wait_for_service(FASTAPI_URL, "FastAPI"):
        shutdown()
    '''
    # 2. Spring Boot
    start_spring()
    if not wait_for_service(SPRING_URL, "Spring Boot"):
        shutdown()
    '''

    # 3. UI
    if not args.no_ui:
        start_ui()
        log_ok("UI iniciada — overlay aparecerá em instantes")

    log_ok("=== Todos os serviços estão rodando ===")
    log("Pressione CTRL+C para encerrar tudo")

    # Mantém o processo vivo monitorando os filhos
    while True:
        for p in processes:
            if p.poll() is not None:
                log_err(f"Um serviço encerrou inesperadamente (PID {p.pid})")
                shutdown()
        time.sleep(3)


if __name__ == "__main__":
    main()
