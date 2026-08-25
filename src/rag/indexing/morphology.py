from functools import lru_cache

from rag.observability.logging import get_logger

logger = get_logger(__name__)


class KiwiMorphAnalyzer:
    """Korean morphological analyzer using kiwipiepy."""

    def __init__(self) -> None:
        self._kiwi = None

    @property
    def kiwi(self):
        if self._kiwi is None:
            from kiwipiepy import Kiwi

            logger.info("loading_kiwi_morph_analyzer")
            self._kiwi = Kiwi()
        return self._kiwi

    def analyze(self, text: str) -> str:
        """Return space-separated morpheme forms for FTS indexing/query."""
        if not text or not text.strip():
            return ""

        tokens = []
        for token in self.kiwi.tokenize(text):
            form = token.form.strip()
            if len(form) > 1 or form.isalnum():
                tokens.append(form)

        return " ".join(tokens) if tokens else text


@lru_cache
def get_morph_analyzer() -> KiwiMorphAnalyzer:
    return KiwiMorphAnalyzer()
