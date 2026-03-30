# Live Captions UI — Fase 1

Overlay de legendas em tempo real com detecção automática de áudio do sistema.

## Pré-requisitos

- Python 3.11+
- **macOS apenas:** instalar o BlackHole → `brew install blackhole-2ch`
- **Windows:** Stereo Mix habilitado nas configurações de som (o app orienta caso necessário)

## Instalação

```bash
# Clone o projeto e entre na pasta
cd live-captions-ui

# Crie um ambiente virtual (recomendado)
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
.venv\Scripts\activate           # Windows

# Instale as dependências
pip install -r requirements.txt
```

## Execução

```bash
python main.py
```

O app detecta automaticamente o dispositivo de áudio do sistema.
Se não detectar, abre uma tela de configuração com instruções.

## Estrutura de arquivos

```
live-captions-ui/
├── main.py                  # Ponto de entrada
├── config.py                # Configurações globais (URL do backend, idiomas etc.)
├── requirements.txt
├── audio/
│   ├── device_detector.py   # Detecta WASAPI loopback (Win) ou BlackHole (Mac)
│   └── capture.py           # Captura contínua de áudio em chunks
└── ui/
    ├── overlay.py           # Janela overlay principal (sempre visível)
    └── onboarding.py        # Tela de configuração quando nenhum dispositivo é encontrado
```

## Variáveis de ambiente

| Variável        | Padrão                    | Descrição                        |
|-----------------|---------------------------|----------------------------------|
| `API_BASE_URL`  | `http://localhost:8080`   | Endereço do Spring Boot backend  |

Para apontar para produção:
```bash
API_BASE_URL=https://api.seuapp.com python main.py
```

## Fase 2 (próximos passos)

- Spring Boot: `POST /api/captions/transcribe` consumido pelo overlay
- FastAPI: endpoints `/transcribe` e `/translate` com Whisper + Argos
