package main.java.com.livecaptions.controller;

import main.java.com.livecaptions.client.AIServiceClient.AIServiceException;
import main.java.com.livecaptions.model.CaptionResponse;
import main.java.com.livecaptions.model.TranscribeRequest;
import main.java.com.livecaptions.service.CaptionService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * Controller REST — único ponto de contato da UI PyQt6 com o backend.
 *
 * Endpoints:
 *   POST /api/captions/transcribe  → processa áudio e retorna legenda
 *   GET  /api/captions/health      → verifica se o backend está vivo
 */
@Slf4j
@RestController
@RequestMapping("/api/captions")
@RequiredArgsConstructor
public class CaptionController {

    private final CaptionService captionService;

    // ── POST /api/captions/transcribe ─────────────────────────────────────────

    /**
     * Recebe chunk de áudio da UI, transcreve e traduz se necessário.
     *
     * Body esperado:
     * {
     *   "audio": "<base64 PCM float32>",
     *   "targetLanguage": "en",
     *   "sampleRate": 16000
     * }
     *
     * Resposta 200:
     * {
     *   "original": "Olá, como vai?",
     *   "translated": "Hello, how are you?",
     *   "detectedLanguage": "pt",
     *   "wasTranslated": true
     * }
     */
    @PostMapping("/transcribe")
    public ResponseEntity<?> transcribe(@Valid @RequestBody TranscribeRequest request) {
        log.debug("Requisição recebida: targetLang={}, sampleRate={}",
                request.getTargetLanguage(), request.getSampleRate());
        try {
            CaptionResponse response = captionService.process(request);
            return ResponseEntity.ok(response);

        } catch (AIServiceException e) {
            log.error("Serviço de IA indisponível: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of(
                            "error", "Serviço de IA indisponível",
                            "detail", e.getMessage()
                    ));

        } catch (Exception e) {
            log.error("Erro inesperado ao processar legenda", e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "Erro interno do servidor"));
        }
    }

    // ── GET /api/captions/health ──────────────────────────────────────────────

    /**
     * Health check simples — a UI chama na inicialização para confirmar
     * que o backend está respondendo antes de começar a capturar áudio.
     */
    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of(
                "status", "ok",
                "service", "live-captions-backend"
        ));
    }
}
