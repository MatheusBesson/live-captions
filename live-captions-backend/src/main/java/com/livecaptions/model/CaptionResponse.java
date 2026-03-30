package main.java.com.livecaptions.model;

import lombok.Builder;
import lombok.Data;

@Data
@Builder
public class CaptionResponse {

    /**
     * Texto transcrito no idioma original detectado pelo Whisper.
     */
    private String original;

    /**
     * Texto traduzido para o idioma alvo.
     * Igual a 'original' quando nenhuma tradução foi necessária.
     */
    private String translated;

    /**
     * Código ISO 639-1 do idioma detectado pelo Whisper ("pt", "en", "es"...).
     */
    private String detectedLanguage;

    /**
     * true se a tradução foi executada, false se idioma == targetLanguage.
     */
    private boolean wasTranslated;
}
