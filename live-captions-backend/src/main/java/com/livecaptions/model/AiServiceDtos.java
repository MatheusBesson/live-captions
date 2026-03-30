package main.java.com.livecaptions.model;

import lombok.Builder;
import lombok.Data;

/**
 * DTOs usados na comunicação interna Spring Boot ↔ FastAPI.
 * Separados dos DTOs públicos da API para isolar contratos.
 */
public class AiServiceDtos {

    // ── Requisição para /transcribe ───────────────────────────────────────────

    @Data
    @Builder
    public static class AiTranscribeRequest {
        private String audio;           // base64 PCM float32
        private Integer sampleRate;     // 16000
    }

    // ── Resposta de /transcribe ───────────────────────────────────────────────

    @Data
    public static class AiTranscribeResponse {
        private String text;            // texto transcrito
        private String language;        // idioma detectado ("pt", "en"...)
        private Double duration;        // duração do áudio em segundos
    }

    // ── Requisição para /translate ────────────────────────────────────────────

    @Data
    @Builder
    public static class AiTranslateRequest {
        private String text;
        private String sourceLang;      // idioma detectado
        private String targetLang;      // idioma desejado pelo usuário
    }

    // ── Resposta de /translate ────────────────────────────────────────────────

    @Data
    public static class AiTranslateResponse {
        private String translated;      // texto traduzido
    }
}
