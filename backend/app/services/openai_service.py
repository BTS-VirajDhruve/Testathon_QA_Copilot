"""OpenAI LLM and embedding service with demo fallback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class OpenAIService:
    """Thin OpenAI wrapper. Falls back to deterministic demo mode without API key."""

    REQUEST_TIMEOUT_SECONDS = 45.0
    MAX_RETRIES = 1

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self.last_chat_backend: str = "unavailable"
        self.last_embed_backend: str = "unavailable"
        if self.settings.has_openai:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self.settings.openai_api_key,
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                    max_retries=self.MAX_RETRIES,
                )
                logger.info(
                    "openai_client_initialized",
                    model=self.settings.openai_model,
                    timeout_s=self.REQUEST_TIMEOUT_SECONDS,
                    # Never log the API key
                    key_configured=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("openai_init_failed", error=str(exc), key_configured=True)
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    @property
    def configured(self) -> bool:
        return self.settings.has_openai

    def diagnostics(self) -> dict[str, Any]:
        return {
            "openai_configured": self.configured,
            "openai_client_ready": self.available,
            "openai_model": self.settings.openai_model if self.configured else None,
            "openai_embedding_model": (
                self.settings.openai_embedding_model if self.configured else None
            ),
            "demo_fallback_enabled": self.settings.enable_demo_fallback,
            "last_chat_backend": self.last_chat_backend,
            "last_embed_backend": self.last_embed_backend,
        }

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        strict: bool = False,
    ) -> dict[str, Any]:
        raw = self.chat(
            system=system,
            user=user,
            temperature=temperature,
            json_mode=True,
            strict=strict,
        )
        return self._parse_json(raw)

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        json_mode: bool = False,
        strict: bool = False,
    ) -> str:
        if self._client is None:
            self.last_chat_backend = "deterministic_fallback"
            if strict:
                raise RuntimeError("OpenAI client unavailable")
            return self._demo_chat(system, user, json_mode=json_mode)

        kwargs: dict[str, Any] = {
            "model": self.settings.openai_model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**kwargs)
            self.last_chat_backend = "openai"
            return response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            # Never include API key material in logs
            logger.error("openai_chat_failed", error=str(exc)[:300])
            self.last_chat_backend = "deterministic_fallback"
            if strict or not self.settings.enable_demo_fallback:
                raise
            return self._demo_chat(system, user, json_mode=json_mode)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self._client is None:
            self.last_embed_backend = "hash_fallback"
            return [self._hash_embed(t) for t in texts]
        try:
            response = self._client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=texts,
            )
            self.last_embed_backend = "openai"
            return [item.embedding for item in response.data]
        except Exception as exc:  # noqa: BLE001
            logger.error("openai_embed_failed", error=str(exc)[:300])
            self.last_embed_backend = "hash_fallback"
            if self.settings.enable_demo_fallback:
                return [self._hash_embed(t) for t in texts]
            raise

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _hash_embed(self, text: str, dims: int = 384) -> list[float]:
        """Deterministic pseudo-embedding for offline/demo mode."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand hash stream
        values: list[float] = []
        seed = digest
        while len(values) < dims:
            seed = hashlib.sha256(seed).digest()
            for byte in seed:
                values.append((byte / 255.0) * 2 - 1)
                if len(values) >= dims:
                    break
        # Light bag-of-words signal so similar words score higher
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % dims
            values[idx] += 0.15
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def _demo_chat(self, system: str, user: str, *, json_mode: bool) -> str:
        """Heuristic responses when OpenAI is unavailable — keeps demo runnable."""
        lower = f"{system}\n{user}".lower()
        if "extract" in lower and ("graph" in lower or "nodes" in lower or "natural language" in lower):
            payload = self._demo_nl_to_graph(user)
            return json.dumps(payload)
        if "critic" in lower or "review" in lower:
            return json.dumps(
                {
                    "approved": True,
                    "notes": [
                        "Ensure each test maps to a concrete graph path.",
                        "Call out uncovered failure paths explicitly.",
                        "Preserve user-provided facts; mark inferences.",
                    ],
                    "improvements": [
                        "Add MFA retry-limit negative case.",
                        "Add OAuth callback timeout scenario.",
                    ],
                }
            )
        if "intent" in lower or "classify" in lower:
            intent = "test_generation"
            if "exploratory" in lower:
                intent = "exploratory"
            elif "regression" in lower or "impact" in lower or "changed" in lower:
                intent = "regression" if "regression" in lower else "impact_analysis"
            elif "coverage" in lower or "gap" in lower:
                intent = "coverage_gap"
            elif "bug" in lower:
                intent = "bug_report"
            return json.dumps({"intent": intent, "confidence": 0.75})
        if json_mode:
            return json.dumps({"result": "demo_mode", "message": "OpenAI unavailable; using deterministic fallback."})
        return "Demo mode: OpenAI API key not configured. Using deterministic QA heuristics."

    def _demo_nl_to_graph(self, user: str) -> dict[str, Any]:
        text = user
        # Pull the NL description after common markers
        match = re.search(r"(?:description|text|input)\s*[:\-]\s*(.+)", text, re.I | re.S)
        body = match.group(1).strip() if match else text
        lower = body.lower()

        root = "Feature"
        if "sign in" in lower or "signin" in lower or "login" in lower:
            root = "Sign In"
        elif "checkout" in lower:
            root = "Checkout"
        elif "payment" in lower:
            root = "Payments"

        branches: list[dict[str, Any]] = []
        patterns = [
            ("email", "Email + Password", False),
            ("password", "Email + Password", False),
            ("google", "Google OAuth", False),
            ("oauth", "Google OAuth", False),
            ("sso", "Enterprise SSO", False),
            ("saml", "SAML", False),
            ("oidc", "OIDC", False),
            ("self-registration", "Self Registration", False),
            ("self registration", "Self Registration", False),
            ("mfa", "MFA", False),
            ("forgot password", "Forgot Password", False),
            ("account lockout", "Account Lockout", True),
            ("provider failure", "Provider Failure", True),
        ]
        seen: set[str] = set()
        for needle, name, failure in patterns:
            if needle in lower and name not in seen:
                seen.add(name)
                branches.append(
                    {
                        "name": name,
                        "type": "FailurePath" if failure else "AuthenticationMethod",
                        "is_failure_path": failure,
                        "inferred": True,
                        "children": [],
                    }
                )

        # Nest MFA / Forgot Password under Email + Password when present
        email = next((b for b in branches if b["name"] == "Email + Password"), None)
        nested_names = {"MFA", "Forgot Password", "Account Lockout"}
        if email:
            kids = [b for b in branches if b["name"] in nested_names]
            email["children"] = [
                {
                    "name": k["name"],
                    "type": "FailurePath" if k["is_failure_path"] else "SubFeature",
                    "is_failure_path": k["is_failure_path"],
                    "inferred": True,
                    "children": [],
                }
                for k in kids
            ]
            branches = [b for b in branches if b["name"] not in nested_names and b["name"] != "Email + Password"]
            branches.insert(0, email)

        return {
            "root": root,
            "description": f"Inferred from natural language (demo mode).",
            "branches": branches,
            "inferred": True,
            "confidence": 0.55,
        }

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
            if fence:
                return json.loads(fence.group(1))
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start : end + 1])
            return {"raw": raw}


_openai_service: OpenAIService | None = None


def get_openai_service() -> OpenAIService:
    global _openai_service
    if _openai_service is None:
        _openai_service = OpenAIService()
    return _openai_service