# Live Captions — Fase 2: Backend

Dois serviços que completam o fluxo de transcrição e tradução ao vivo.

---

## Estrutura completa do projeto

```
live-captions/
├── start.py                          ← inicia tudo com um comando
│
├── live-captions-ui/                 ← Fase 1 (PyQt6)
│
├── live-captions-backend/            ← Spring Boot (porta 8080)
│   ├── pom.xml
│   └── src/main/java/com/livecaptions/
│       ├── LiveCaptionsApplication.java
│       ├── controller/
│       │   └── CaptionController.java
│       ├── service/
│       │   └── CaptionService.java
│       ├── client/
│       │   └── AIServiceClient.java
│       ├── model/
│       │   ├── TranscribeRequest.java
│       │   ├── CaptionResponse.java
│       │   └── AiServiceDtos.java
│       ├── config/
│       │   └── AppConfig.java
│       └── resources/
│           └── application.yml
│
└── live-captions-fastapi/            ← FastAPI Python (porta 8001)
    ├── main.py
    ├── requirements.txt
    ├── routers/
    │   ├── transcribe.py             ← POST /transcribe
    │   └── translate.py              ← POST /translate
    ├── services/
    │   ├── whisper_service.py        ← faster-whisper
    │   └── argos_service.py          ← Argos Translate
    └── models/
        └── schemas.py
```

---

## Pré-requisitos

| Ferramenta  | Versão mínima | Verificar com         |
|-------------|---------------|-----------------------|
| Python      | 3.11+         | `python --version`    |
| Java        | 21+           | `java --version`      |
| Maven       | 3.9+          | `mvn --version`       |
| ffmpeg      | qualquer      | `ffmpeg -version`     |

> **ffmpeg** é necessário para o Whisper decodificar áudio.
> - macOS: `brew install ffmpeg`
> - Windows: baixe em https://ffmpeg.org/download.html e adicione ao PATH

---

## Setup — FastAPI

```bash
cd live-captions-fastapi

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Inicia o servidor (porta 8001)
uvicorn main:app --port 8001 --reload
```

Na **primeira execução**, o Whisper baixa o modelo (~244MB) e o Argos
baixa os pacotes de idioma (~100MB por par). Isso ocorre uma única vez.

---

## Setup — Spring Boot

```bash
cd live-captions-backend

# Compila e empacota
mvn package -q

# Inicia o servidor (porta 8080)
java -jar target/live-captions-backend-0.1.0.jar
```

---

## Iniciar tudo de uma vez

Com os dois backends configurados, basta rodar na raiz do projeto:

```bash
python start.py
```

Isso inicia FastAPI → aguarda health check → inicia Spring Boot →
aguarda health check → abre a UI. CTRL+C encerra tudo de forma limpa.

Para rodar só os backends (sem UI, útil para testar com curl):

```bash
python start.py --no-ui
```

---

## Testar manualmente com curl

**Health check Spring Boot:**
```bash
curl http://localhost:8080/api/captions/health
# {"status":"ok","service":"live-captions-backend"}
```

**Health check FastAPI:**
```bash
curl http://localhost:8001/health
# {"status":"ok","whisper":"loaded","argos":"loaded"}
```

**Transcrição (com áudio fictício para testar o fluxo):**
```bash
curl -X POST http://localhost:8080/api/captions/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio":"AAAA","targetLanguage":"en","sampleRate":16000}'
```

---

## Variáveis de configuração

Edite `live-captions-backend/src/main/resources/application.yml`:

```yaml
ai:
  service:
    url: http://localhost:8001     # troque pelo URL de produção no SaaS
    timeout-seconds: 15
```

---

## Fluxo completo de uma requisição

```
PyQt6 (captura áudio)
  └─► POST :8080/api/captions/transcribe  {audio, targetLanguage}
        └─► CaptionController → CaptionService → AIServiceClient
              └─► POST :8001/transcribe  {audio, sampleRate}
                    └─► WhisperService → {text, language}
              └─► [se idioma != targetLanguage]
                    POST :8001/translate  {text, sourceLang, targetLang}
                    └─► ArgosService → {translated}
        └─► CaptionResponse {original, translated, detectedLanguage}
  └─► UI exibe legenda no overlay
```

---

## Próximos passos — Fase 3 e 4

| Fase | O que adicionar                                      |
|------|------------------------------------------------------|
| 3    | Ajustar modelo Whisper para `medium` (mais precisão) |
| 4    | Mais pares de idioma no Argos                        |
| 5    | Auth JWT no Spring Boot para o SaaS                  |
| 6    | PostgreSQL para histórico de transcrições            |
