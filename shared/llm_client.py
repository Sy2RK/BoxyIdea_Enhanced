#!/usr/bin/env python3
"""Unified LLM client supporting OpenAI, OpenRouter, and Google AI Studio."""

import os
import sys


class LLMClient:
    """LLM client that wraps OpenAI, OpenRouter, or Google AI Studio.

    Configure via environment variables:
      LLM_PROVIDER=openai|openrouter|google   (default: openai)
      Only one provider is active per run.

    For OpenAI (default):
      OPENAI_API_KEY or LLM_API_KEY
      OPENAI_MODEL   (default: gpt-5.4-mini)
      OPENAI_MODEL_DROP

    For OpenRouter:
      OPENROUTER_API_KEY or LLM_API_KEY
      OPENROUTER_MODEL   (default: anthropic/claude-sonnet-4-20250514)
      OPENROUTER_MODEL_DROP

    For Google AI Studio:
      GOOGLE_API_KEY or LLM_API_KEY
      GOOGLE_MODEL       (default: gemini-3.1-flash-lite-preview)
      GOOGLE_MODEL_DROP

    Note:
      *_MODEL_DROP is a fallback model within the same provider.
      It does not switch providers automatically.
    """

    def __init__(self):
        self.provider = os.environ.get("LLM_PROVIDER", "openai").lower().strip()
        if self.provider == "openai":
            self._init_openai()
        elif self.provider == "google":
            self._init_google()
        elif self.provider == "openrouter":
            self._init_openrouter()
        else:
            raise RuntimeError(
                "Unsupported LLM_PROVIDER. Expected one of: openai, openrouter, google"
            )

    def _init_openai(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "OpenAI provider selected but openai is not installed. "
                "Run: pip install openai"
            )

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OpenAI API key not found. Set OPENAI_API_KEY or LLM_API_KEY in .env"
            )
        self.client = OpenAI(api_key=api_key)
        self.model = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
        self.fallback = os.environ.get("OPENAI_MODEL_DROP")

    def _init_openrouter(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError(
                "OpenRouter provider selected but openai is not installed. "
                "Run: pip install openai"
            )

        api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OpenRouter API key not found. Set OPENROUTER_API_KEY or LLM_API_KEY in .env"
            )
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
        )
        self.model = os.environ.get(
            "OPENROUTER_MODEL", "anthropic/claude-sonnet-4-20250514"
        )
        self.fallback = os.environ.get("OPENROUTER_MODEL_DROP")

    def _init_google(self):
        try:
            from google import genai
        except ImportError:
            raise RuntimeError(
                "Google AI Studio provider selected but google-genai is not installed. "
                "Run: pip install google-genai"
            )
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("LLM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "Google API key not found. Set GOOGLE_API_KEY or LLM_API_KEY in .env"
            )
        self.client = genai.Client(api_key=api_key)
        self.model = os.environ.get("GOOGLE_MODEL", "gemini-3.1-flash-lite-preview")
        self.fallback = os.environ.get("GOOGLE_MODEL_DROP")

    def call(
        self,
        prompt,
        system_message="",
        model=None,
        fallback_model=None,
        temperature=0.7,
        max_tokens=2048,
        timeout=120,
    ):
        """Call the LLM and return response text.

        Args:
            prompt: The user message content.
            system_message: Optional instruction message.
            model: Override the default model from .env.
            fallback_model: Override the default fallback model.
            temperature: Sampling temperature.
            max_tokens: Maximum output tokens.
            timeout: Request timeout in seconds (OpenAI / OpenRouter only).
        """
        model = model or self.model
        fallback = fallback_model or self.fallback

        if self.provider == "google":
            return self._call_google(
                prompt, system_message, model, fallback, temperature, max_tokens
            )
        if self.provider == "openrouter":
            return self._call_openrouter(
                prompt, system_message, model, fallback, temperature, max_tokens, timeout
            )
        return self._call_openai(
            prompt, system_message, model, fallback, temperature, max_tokens, timeout
        )

    def _build_chat_messages(self, prompt, system_message, instruction_role):
        messages = []
        if system_message:
            messages.append({"role": instruction_role, "content": system_message})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _extract_chat_text(self, response):
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                else:
                    text = getattr(item, "text", None)
                if text:
                    parts.append(text)
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    def _is_unsupported_temperature_error(self, error):
        text = str(error).lower()
        return "temperature" in text and "unsupported" in text

    def _call_openai(
        self, prompt, system_message, model, fallback, temperature, max_tokens, timeout
    ):
        messages = self._build_chat_messages(prompt, system_message, "developer")
        request = {
            "model": model,
            "messages": messages,
            "max_completion_tokens": max_tokens,
            "timeout": timeout,
        }
        if temperature is not None:
            request["temperature"] = temperature

        try:
            response = self.client.chat.completions.create(**request)
            return self._extract_chat_text(response)
        except Exception as primary_err:
            if "temperature" in request and self._is_unsupported_temperature_error(primary_err):
                print(
                    "  [!] Model rejected custom temperature; retrying with provider default",
                    file=sys.stderr,
                )
                request.pop("temperature", None)
                response = self.client.chat.completions.create(**request)
                return self._extract_chat_text(response)
            if fallback:
                print(
                    f"  [!] Primary model failed: {primary_err}, trying fallback: {fallback}",
                    file=sys.stderr,
                )
                request["model"] = fallback
                response = self.client.chat.completions.create(**request)
                return self._extract_chat_text(response)
            raise

    def _call_openrouter(
        self, prompt, system_message, model, fallback, temperature, max_tokens, timeout
    ):
        messages = self._build_chat_messages(prompt, system_message, "system")

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            return self._extract_chat_text(response)
        except Exception as primary_err:
            if fallback:
                print(
                    f"  [!] Primary model failed: {primary_err}, trying fallback: {fallback}",
                    file=sys.stderr,
                )
                response = self.client.chat.completions.create(
                    model=fallback,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
                return self._extract_chat_text(response)
            raise

    def _call_google(
        self, prompt, system_message, model, fallback, temperature, max_tokens
    ):
        from google import genai

        contents = prompt
        if system_message:
            contents = f"{system_message}\n\n{prompt}"

        config = genai.types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response.text
        except Exception as primary_err:
            if fallback:
                print(
                    f"  [!] Primary model failed: {primary_err}, trying fallback: {fallback}",
                    file=sys.stderr,
                )
                response = self.client.models.generate_content(
                    model=fallback,
                    contents=contents,
                    config=config,
                )
                return response.text
            raise
