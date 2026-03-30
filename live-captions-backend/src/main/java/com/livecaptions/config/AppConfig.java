package main.java.com.livecaptions.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.time.Duration;

@Configuration
public class AppConfig {

    @Value("${ai.service.timeout-seconds:15}")
    private int aiTimeoutSeconds;

    /**
     * RestTemplate configurado com timeout explícito.
     * Evita que uma lentidão do FastAPI trave threads do Spring indefinidamente.
     */
    @Bean
    public RestTemplate restTemplate(RestTemplateBuilder builder) {
        return builder
                .setConnectTimeout(Duration.ofSeconds(5)) // set added
                .setReadTimeout(Duration.ofSeconds  (aiTimeoutSeconds)) // set added
                .build();
    }

    /**
     * CORS — permite chamadas da UI PyQt6 (que usa localhost) e,
     * futuramente, do frontend web do SaaS.
     * Em produção, substitua "*" pelo domínio real.
     */
    @Bean
    public WebMvcConfigurer corsConfigurer() {
        return new WebMvcConfigurer() {
            @Override
            public void addCorsMappings(CorsRegistry registry) {
                registry.addMapping("/api/**")
                        .allowedOriginPatterns("http://localhost:*", "https://*.seuapp.com")
                        .allowedMethods("GET", "POST", "OPTIONS")
                        .allowedHeaders("*");
            }
        };
    }
}
