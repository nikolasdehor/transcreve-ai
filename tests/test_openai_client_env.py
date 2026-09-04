"""
Garante que OPENAI_API_KEY/OPENAI_BASE_URL herdados do shell (router Verboo,
proxy corporativo) nao desviam o provider OpenAI do TranscreveAI.

Caso real (2026-09-04): o shell exportava chave `vbk_` + base_url da Verboo e o
SDK herdou os dois em silencio; Whisper e embeddings voltaram 401.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from video_kb.ai import openai_available
from video_kb.providers.openai_provider import OFFICIAL_OPENAI_BASE_URL, OpenAIProvider


class OpenAIClientEnvTest(unittest.TestCase):
    def test_video_kb_vars_vencem_env_global_e_base_url_e_oficial(self) -> None:
        env = {
            "OPENAI_API_KEY": "vbk_de_outro_produto",
            "OPENAI_BASE_URL": "https://router.example/v1",
            "VIDEO_KB_OPENAI_API_KEY": "sk-test-transcreveai",
            "VIDEO_KB_OPENAI_BASE_URL": "",
        }
        with patch.dict("os.environ", env, clear=False):
            client = OpenAIProvider()._get_client()

        self.assertEqual(client.api_key, "sk-test-transcreveai")
        self.assertEqual(str(client.base_url).rstrip("/"), OFFICIAL_OPENAI_BASE_URL)

    def test_openai_api_key_generica_ainda_serve_de_fallback(self) -> None:
        env = {
            "OPENAI_API_KEY": "sk-generica",
            "OPENAI_BASE_URL": "https://router.example/v1",
            "VIDEO_KB_OPENAI_API_KEY": "",
            "VIDEO_KB_OPENAI_BASE_URL": "https://meu-proxy.example/v1",
        }
        with patch.dict("os.environ", env, clear=False):
            self.assertTrue(openai_available())
            client = OpenAIProvider()._get_client()

        self.assertEqual(client.api_key, "sk-generica")
        self.assertEqual(str(client.base_url).rstrip("/"), "https://meu-proxy.example/v1")


if __name__ == "__main__":
    unittest.main()
