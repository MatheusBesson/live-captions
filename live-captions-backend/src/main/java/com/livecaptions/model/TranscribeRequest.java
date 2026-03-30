package main.java.com.livecaptions.model;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

@Data
public class TranscribeRequest {

    /**
     * Áudio capturado pela UI em base64 (PCM float32, 16kHz, mono).
     */
    @NotBlank(message = "O campo 'audio' não pode estar vazio")
    private String audio;

    /**
     * Idioma alvo para tradução (código ISO 639-1: "en", "pt", "es"...).
     * Se null ou igual ao idioma detectado, a tradução é pulada.
     */
    private String targetLanguage;

    /**
     * Sample rate do áudio enviado — padrão 16000 Hz (Whisper).
     */
    @NotNull
    private Integer sampleRate = 16000;
}
