package main.java.com.livecaptions.service;

import main.java.com.livecaptions.client.AIServiceClient;
import main.java.com.livecaptions.client.AIServiceClient.AIServiceException;
import main.java.com.livecaptions.model.AiServiceDtos.AiTranscribeResponse;
import main.java.com.livecaptions.model.AiServiceDtos.AiTranslateResponse;
import main.java.com.livecaptions.model.CaptionResponse;
import main.java.com.livecaptions.model.TranscribeRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

/**
 * Orquestra o fluxo completo de geração de legendas:
 *
 * 1. Envia áudio para o FastAPI → obtém texto transcrito + idioma detectado
 * 2. Compara idioma detectado com o idioma alvo do usuário
 * 3. Se diferentes → chama tradução
 * 4. Monta e retorna CaptionResponse para o controller
 *
 * Toda decisão de negócio fica aqui. O AIServiceClient só faz HTTP.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CaptionService {

    private final AIServiceClient aiServiceClient;

    public CaptionResponse process(TranscribeRequest request) {
        // ── Passo 1: Transcrição ──────────────────────────────────────────────
        AiTranscribeResponse transcription;
        try {
            transcription = aiServiceClient.transcribe(
                    request.getAudio(),
                    request.getSampleRate()
            );
        } catch (AIServiceException e) {
            log.error("Falha na transcrição: {}", e.getMessage());
            throw e; // Deixa o GlobalExceptionHandler tratar
        }

        String originalText = transcription.getText();
        String detectedLang = transcription.getLanguage();

        // Áudio sem fala detectada — retorna vazio sem chamar tradução
        if (!StringUtils.hasText(originalText)) {
            log.debug("Nenhuma fala detectada no chunk de áudio");
            return CaptionResponse.builder()
                    .original("")
                    .translated("")
                    .detectedLanguage(detectedLang)
                    .wasTranslated(false)
                    .build();
        }

        // ── Passo 2: Decidir se traduz ────────────────────────────────────────
        String targetLang = request.getTargetLanguage();
        boolean shouldTranslate = StringUtils.hasText(targetLang)
                && StringUtils.hasText(detectedLang)
                && !targetLang.equalsIgnoreCase(detectedLang);

        if (!shouldTranslate) {
            log.debug("Tradução não necessária: detectado={}, alvo={}", detectedLang, targetLang);
            return CaptionResponse.builder()
                    .original(originalText)
                    .translated(originalText)
                    .detectedLanguage(detectedLang)
                    .wasTranslated(false)
                    .build();
        }

        // ── Passo 3: Tradução ─────────────────────────────────────────────────
        String translatedText;
        try {
            AiTranslateResponse translation = aiServiceClient.translate(
                    originalText, detectedLang, targetLang
            );
            translatedText = translation.getTranslated();
        } catch (AIServiceException e) {
            // Falha na tradução não deve quebrar o app — exibe original
            log.warn("Falha na tradução, exibindo original: {}", e.getMessage());
            translatedText = originalText;
        }

        log.debug("Legenda gerada: [{}→{}] '{}' → '{}'",
                detectedLang, targetLang, originalText, translatedText);

        return CaptionResponse.builder()
                .original(originalText)
                .translated(translatedText)
                .detectedLanguage(detectedLang)
                .wasTranslated(true)
                .build();
    }
}
