"""
security.py: Security Shields using Microsoft Presidio.
Detects and anonymizes PII (Personally Identifiable Information) in LLM inputs/outputs.
"""

from __future__ import annotations

import os
from loguru import logger

try:
    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine
    _PRESIDIO_AVAILABLE = True
except ImportError:
    _PRESIDIO_AVAILABLE = False
    logger.warning("Presidio not installed. PII shielding is disabled.")

ENABLE_PII_SHIELD = os.getenv("ENABLE_PII_SHIELD", "true").lower() == "true"

class SecurityShield:
    def __init__(self):
        self._analyzer = None
        self._anonymizer = None
        self._enabled = ENABLE_PII_SHIELD and _PRESIDIO_AVAILABLE

    def initialize(self):
        if not self._enabled:
            logger.info("Security Shield (PII) is disabled or missing dependencies.")
            return

        try:
            logger.info("Initializing Presidio Analyzer & Anonymizer...")
            self._analyzer = AnalyzerEngine()
            self._anonymizer = AnonymizerEngine()
            logger.info("Security Shield (PII) initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Security Shield: {e}")
            self._enabled = False

    def sanitize_text(self, text: str) -> str:
        """Scan and anonymize PII in the given text."""
        if not self._enabled or not text:
            return text

        try:
            # Analyze text for PII
            results = self._analyzer.analyze(
                text=text,
                entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN"],
                language="en",
                score_threshold=0.6
            )
            
            # Anonymize findings
            if results:
                anonymized = self._anonymizer.anonymize(text=text, analyzer_results=results)
                return anonymized.text
            return text
        except Exception as e:
            logger.error(f"PII sanitization failed: {e}")
            # Fail open to prevent blocking the workflow
            return text

security_shield = SecurityShield()
