package main.java.com.livecaptions.client;

import main.java.com.livecaptions.model.AiServiceDtos.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestTemplate;

/**
 * Cliente HTTP que encapsula toda comunicação com o microsserviço FastAPI.
 *
 * Isolado em uma classe própria para que:
 * - O CaptionService não conheça URLs nem detalhes HTTP
 * - Trocar de localhost para produção seja uma linha no application.yml
 * - Mockar nos testes seja trivial
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AIServiceClient {

    private final RestTemplate restTemplate;

    @Value("${ai.service.url}")
    private String aiServiceUrl;

    // ── Transcrição ───────────────────────────────────────────────────────────

    /**
     * Envia áudio em base64 para o FastAPI transcrever via Whisper.
     *
     * @param audio      áudio codificado em base64 (PCM float32, 16kHz, mono)
     * @param sampleRate taxa de amostragem (normalmente 16000)
     * @return resposta com texto transcrito e idioma detectado
     * @throws AIServiceException se o FastAPI estiver offline ou retornar erro
     */
    public AiTranscribeResponse transcribe(String audio, int sampleRate) {
        String url = aiServiceUrl + "/transcribe";
        AiTranscribeRequest request = AiTranscribeRequest.builder()
                .audio(audio)
                .sampleRate(sampleRate)
                .build();

        log.debug("Enviando áudio para transcrição → {}", url);
        try {
            ResponseEntity<AiTranscribeResponse> response =
                    restTemplate.postForEntity(url, request, AiTranscribeResponse.class);

            if (response.getBody() == null) {
                throw new AIServiceException("Resposta vazia do serviço de transcrição");
            }
            log.debug("Transcrição recebida: lang={}, texto={}",
                    response.getBody().getLanguage(),
                    response.getBody().getText());
            return response.getBody();

        } catch (ResourceAccessException e) {
            throw new AIServiceException(
                    "Não foi possível conectar ao serviço de IA em " + url +
                    ". Verifique se o FastAPI está rodando.", e);
        }
    }

    // ── Tradução ──────────────────────────────────────────────────────────────

    /**
     * Envia texto para o FastAPI traduzir via Argos Translate.
     *
     * @param text       texto a traduzir
     * @param sourceLang idioma detectado pelo Whisper ("pt", "en"...)
     * @param targetLang idioma alvo escolhido pelo usuário
     * @return resposta com texto traduzido
     * @throws AIServiceException se o FastAPI estiver offline ou retornar erro
     */
    public AiTranslateResponse translate(String text, String sourceLang, String targetLang) {
        String url = aiServiceUrl + "/translate";
        AiTranslateRequest request = AiTranslateRequest.builder()
                .text(text)
                .sourceLang(sourceLang)
                .targetLang(targetLang)
                .build();

        log.debug("Enviando texto para tradução: {} → {} | {}", sourceLang, targetLang, url);
        try {
            ResponseEntity<AiTranslateResponse> response =
                    restTemplate.postForEntity(url, request, AiTranslateResponse.class);

            if (response.getBody() == null) {
                throw new AIServiceException("Resposta vazia do serviço de tradução");
            }
            return response.getBody();

        } catch (ResourceAccessException e) {
            throw new AIServiceException(
                    "Não foi possível conectar ao serviço de IA em " + url, e);
        }
    }

    // ── Exception interna ─────────────────────────────────────────────────────

    public static class AIServiceException extends RuntimeException {
        public AIServiceException(String message) { super(message); }
        public AIServiceException(String message, Throwable cause) { super(message, cause); }
    }
}
