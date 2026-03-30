"""
Integração com Argos Translate para tradução offline.

Pacotes de idioma são baixados automaticamente na primeira execução
e ficam armazenados em disco (~100MB por par de idiomas).
"""

import logging

logger = logging.getLogger(__name__)

try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False
    logger.warning("argostranslate não instalado. Usando modo stub.")

# Pares de idiomas que serão baixados automaticamente na inicialização
# Adicione mais conforme necessário — cada par usa ~100MB de disco
DEFAULT_LANGUAGE_PAIRS = [
    ("pt", "en"),
    ("en", "pt"),
    ("pt", "es"),
    ("es", "pt"),
    ("en", "es"),
    ("es", "en"),
    ("en", "fr"),
    ("fr", "en"),
    ("fr", "pt"),
    ("pt", "fr"),
    ("en", "de"),
    ("de", "en"),
]


class ArgosService:

    def __init__(self):
        self._initialized = False

    def load(self, pairs: list[tuple[str, str]] = None):
        """
        Verifica e instala os pacotes de idioma necessários.
        Chamado uma vez na inicialização do FastAPI.

        Pacotes já baixados não são re-baixados.
        """
        if not ARGOS_AVAILABLE:
            logger.warning("[ArgosService] argostranslate indisponível — modo stub ativo")
            return

        pairs = pairs or DEFAULT_LANGUAGE_PAIRS
        logger.info(f"[ArgosService] Verificando pacotes para {len(pairs)} pares de idiomas...")

        # Atualiza índice de pacotes disponíveis
        argostranslate.package.update_package_index()
        available = argostranslate.package.get_available_packages()

        for source, target in pairs:
            installed = argostranslate.translate.get_installed_languages()
            installed_codes = {lang.code for lang in installed}

            if source in installed_codes and target in installed_codes:
                # Verifica se o par específico está instalado
                source_lang = next((l for l in installed if l.code == source), None)
                if source_lang:
                    translation = source_lang.get_translation(
                        next((l for l in installed if l.code == target), None)
                    )
                    if translation:
                        logger.debug(f"[ArgosService] Par {source}→{target} já instalado")
                        continue

            # Baixa e instala o pacote
            pkg = next(
                (p for p in available
                 if p.from_code == source and p.to_code == target),
                None,
            )
            if pkg:
                logger.info(f"[ArgosService] Baixando pacote {source}→{target}...")
                argostranslate.package.install_from_path(pkg.download())
                logger.info(f"[ArgosService] Pacote {source}→{target} instalado")
            else:
                logger.warning(f"[ArgosService] Par {source}→{target} não disponível no índice")

        self._initialized = True
        logger.info("[ArgosService] Pronto")

    def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        """
        Traduz texto do idioma de origem para o idioma alvo.

        Retorna o texto original se a tradução falhar,
        para garantir que a legenda nunca fique em branco.
        """
        if not ARGOS_AVAILABLE or not self._initialized:
            return f"[tradução indisponível] {text}"

        if not text.strip():
            return text

        try:
            installed = argostranslate.translate.get_installed_languages()

            source = next((l for l in installed if l.code == source_lang), None)
            target = next((l for l in installed if l.code == target_lang), None)

            if not source or not target:
                logger.warning(
                    f"[ArgosService] Idioma não instalado: {source_lang} ou {target_lang}"
                )
                return text

            translation = source.get_translation(target)
            if not translation:
                logger.warning(f"[ArgosService] Par {source_lang}→{target_lang} não instalado")
                return text

            result = translation.translate(text)
            logger.debug(f"[ArgosService] '{text[:40]}...' → '{result[:40]}...'")
            return result

        except Exception as e:
            logger.error(f"[ArgosService] Erro ao traduzir: {e}")
            return text  # Fallback seguro: retorna original


# Instância singleton
argos_service = ArgosService()
