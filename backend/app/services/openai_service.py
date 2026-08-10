"""OpenAI LLM and embedding service with demo fallback and task-aware model routing."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.enums import LLMTaskType
from app.services.model_router import (
    ModelRoutingContext,
    ModelSelection,
    get_model_router,
)

logger = get_logger(__name__)

_MODEL_UNAVAILABLE_MARKERS = (
    "model_not_found",
    "does not exist",
    "invalid model",
    "model is not available",
    "you do not have access",
    "not have access to model",
    "unsupported model",
    "unknown model",
)


class OpenAIService:
    """Thin OpenAI wrapper. Falls back to deterministic demo mode without API key."""

    REQUEST_TIMEOUT_SECONDS = 45.0
    MAX_RETRIES = 1

    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None
        self.last_chat_backend: str = "unavailable"
        self.last_embed_backend: str = "unavailable"
        self.last_chat_model: str | None = None
        self.last_requested_model: str | None = None
        self.last_task_type: str | None = None
        self.last_routing: dict[str, Any] = {}
        self.routing_events: list[dict[str, Any]] = []
        self._unavailable_models: set[str] = set()
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
                    key_configured=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "openai_init_failed", error=str(exc), key_configured=True
                )
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
            "model_routing_enabled": self.settings.model_routing_enabled,
            "model_escalation_enabled": self.settings.model_escalation_enabled,
            "model_reviewer_enabled": self.settings.model_reviewer_enabled,
            "last_chat_backend": self.last_chat_backend,
            "last_embed_backend": self.last_embed_backend,
            "last_chat_model": self.last_chat_model,
            "last_requested_model": self.last_requested_model,
            "last_task_type": self.last_task_type,
            "last_routing": self.last_routing or None,
            "routing_events": list(self.routing_events[-12:]),
        }

    def clear_routing_events(self) -> None:
        self.routing_events = []
        self.last_routing = {}

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        strict: bool = False,
        task_type: LLMTaskType | None = None,
        routing_context: ModelRoutingContext | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        raw = self.chat(
            system=system,
            user=user,
            temperature=temperature,
            json_mode=True,
            strict=strict,
            task_type=task_type,
            routing_context=routing_context,
            model_override=model_override,
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
        task_type: LLMTaskType | None = None,
        routing_context: ModelRoutingContext | None = None,
        model_override: str | None = None,
    ) -> str:
        selection = self._resolve_selection(task_type, routing_context, model_override)
        self.last_task_type = selection.requested_task_type.value if selection else None
        self.last_requested_model = (
            selection.selected_model if selection else self.settings.openai_model
        )

        if self._client is None:
            self.last_chat_backend = "deterministic_fallback"
            self.last_chat_model = None
            self._record_routing_event(
                selection=selection,
                actual_model=None,
                backend="deterministic_fallback",
                fallback_used=True,
                success=False,
                latency_ms=0,
                error="openai_client_unavailable",
            )
            if strict:
                raise RuntimeError("OpenAI client unavailable")
            return self._demo_chat(system, user, json_mode=json_mode)

        models_to_try = self._models_to_try(selection)
        last_error: str | None = None
        started = time.perf_counter()

        for idx, model_name in enumerate(models_to_try):
            if model_name in self._unavailable_models:
                continue
            kwargs: dict[str, Any] = {
                "model": model_name,
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
                latency_ms = int((time.perf_counter() - started) * 1000)
                content = response.choices[0].message.content or ""
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "prompt_tokens", None) if usage else None
                output_tokens = (
                    getattr(usage, "completion_tokens", None) if usage else None
                )
                self.last_chat_backend = "openai"
                self.last_chat_model = model_name
                fallback_used = bool(
                    selection and model_name != selection.selected_model
                )
                self._record_routing_event(
                    selection=selection,
                    actual_model=model_name,
                    backend="openai",
                    fallback_used=fallback_used,
                    success=True,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                return content
            except Exception as exc:  # noqa: BLE001
                err = str(exc)[:300]
                last_error = err
                if self._is_model_unavailable_error(err):
                    self._unavailable_models.add(model_name)
                    logger.warning(
                        "openai_model_unavailable",
                        model=model_name,
                        error=err,
                        will_fallback=idx + 1 < len(models_to_try),
                    )
                    continue
                logger.error("openai_chat_failed", model=model_name, error=err)
                break

        latency_ms = int((time.perf_counter() - started) * 1000)
        self.last_chat_backend = "deterministic_fallback"
        self.last_chat_model = None
        self._record_routing_event(
            selection=selection,
            actual_model=None,
            backend="deterministic_fallback",
            fallback_used=True,
            success=False,
            latency_ms=latency_ms,
            error=(last_error or "openai_chat_failed")[:200],
        )
        if strict or not self.settings.enable_demo_fallback:
            raise RuntimeError(last_error or "OpenAI chat failed")
        return self._demo_chat(system, user, json_mode=json_mode)

    def _resolve_selection(
        self,
        task_type: LLMTaskType | None,
        routing_context: ModelRoutingContext | None,
        model_override: str | None,
    ) -> ModelSelection | None:
        if model_override:
            tt = task_type or LLMTaskType.TEST_CASE_GENERATION
            return ModelSelection(
                requested_task_type=tt,
                selected_model=model_override,
                base_model=model_override,
                fallback_model=self.settings.openai_model,
                routing_enabled_for_task=False,
            )
        if task_type is None:
            return ModelSelection(
                requested_task_type=LLMTaskType.TEST_CASE_GENERATION,
                selected_model=self.settings.openai_model,
                base_model=self.settings.openai_model,
                fallback_model=self.settings.openai_model,
                routing_enabled_for_task=False,
            )
        return get_model_router().resolve_model(task_type, routing_context)

    def _models_to_try(self, selection: ModelSelection | None) -> list[str]:
        ordered: list[str] = []
        if selection:
            ordered.append(selection.selected_model)
            if selection.fallback_model and selection.fallback_model not in ordered:
                ordered.append(selection.fallback_model)
        if self.settings.openai_model not in ordered:
            ordered.append(self.settings.openai_model)
        # Deduplicate while preserving order
        seen: set[str] = set()
        result: list[str] = []
        for m in ordered:
            if m and m not in seen:
                seen.add(m)
                result.append(m)
        return result

    @staticmethod
    def _is_model_unavailable_error(message: str) -> bool:
        lower = message.lower()
        return any(marker in lower for marker in _MODEL_UNAVAILABLE_MARKERS)

    def _record_routing_event(
        self,
        *,
        selection: ModelSelection | None,
        actual_model: str | None,
        backend: str,
        fallback_used: bool,
        success: bool,
        latency_ms: int,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "task_type": selection.requested_task_type.value if selection else None,
            "base_model": selection.base_model
            if selection
            else self.settings.openai_model,
            "selected_model": selection.selected_model
            if selection
            else self.settings.openai_model,
            "actual_model_used": actual_model,
            "escalated": selection.escalated if selection else False,
            "escalation_reason": selection.escalation_reason if selection else None,
            "fallback_used": fallback_used,
            "reviewer_triggered": selection.reviewer_required if selection else False,
            "reviewer_reasons": list(selection.reviewer_reasons) if selection else [],
            "routing_policy_version": selection.routing_policy_version
            if selection
            else None,
            "backend": backend,
            "success": success,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "error": error,
        }
        self.last_routing = event
        self.routing_events.append(event)
        if self.settings.model_routing_log_enabled:
            logger.info(
                "model_invocation",
                task_type=event["task_type"],
                selected_model=event["selected_model"],
                actual_model_used=event["actual_model_used"],
                escalated=event["escalated"],
                fallback_used=event["fallback_used"],
                backend=backend,
                success=success,
                latency_ms=latency_ms,
                # Never log prompts or API keys
            )
        return event

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
        values: list[float] = []
        seed = digest
        while len(values) < dims:
            seed = hashlib.sha256(seed).digest()
            for byte in seed:
                values.append((byte / 255.0) * 2 - 1)
                if len(values) >= dims:
                    break
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        for token in tokens:
            idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % dims
            values[idx] += 0.15
        norm = math.sqrt(sum(v * v for v in values)) or 1.0
        return [v / norm for v in values]

    def _demo_chat(self, system: str, user: str, *, json_mode: bool) -> str:
        """Heuristic responses when OpenAI is unavailable — keeps demo runnable."""
        lower = f"{system}\n{user}".lower()
        # Lightweight node classification table (new NL pipeline) — never emit graph JSON.
        if "classify each" in lower and ("node type" in lower or "node name" in lower):
            return self._demo_classify_nodes(user)
        if "extract" in lower and (
            "graph" in lower or "nodes" in lower or "natural language" in lower
        ):
            # Legacy path: kept for any remaining callers; prefer classification-only demos.
            if "do not generate json" in lower or "classification table" in lower:
                return self._demo_classify_nodes(user)
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
            return json.dumps(
                {
                    "result": "demo_mode",
                    "message": "OpenAI unavailable; using deterministic fallback.",
                }
            )
        return "Demo mode: OpenAI API key not configured. Using deterministic QA heuristics."

    def _demo_classify_nodes(self, user: str) -> str:
        """Return Node | Type table for low-confidence classification demos."""
        from app.graph.node_typing import infer_node_type

        names: list[str] = []
        for line in user.splitlines():
            line = line.strip().lstrip("-* ").strip()
            if not line or line.lower().startswith("classify"):
                continue
            names.append(line)
        if not names:
            # Fallback: extract capitalized phrases
            names = re.findall(r"[A-Z][A-Za-z0-9+\-_/ ]{1,48}", user)[:20]

        rows = ["Node Name | Node Type"]
        for name in names:
            ntype = infer_node_type(
                name, is_failure="fail" in name.lower() or "timeout" in name.lower()
            )
            rows.append(f"{name} | {ntype.value}")
        return "\n".join(rows)

    def _demo_nl_to_graph(self, user: str) -> dict[str, Any]:
        text = user
        match = re.search(
            r"(?:description|text|input)\s*[:\-]\s*(.+)", text, re.I | re.S
        )
        body = match.group(1).strip() if match else text
        lower = body.lower()

        root = "Feature"
        explicit = re.search(
            r"(?:root(?:\s+feature)?|\bfeature\b|\bflow\b|\bfor\b)\s*[:\-]?\s*['\"]?([A-Za-z][\w\s+\-/]{1,60})",
            body,
            re.I,
        )
        if explicit:
            candidate = explicit.group(1).strip(" .,\"'")
            candidate = re.split(r"[.;\n]", candidate)[0].strip()
            if 1 < len(candidate) <= 48:
                root = candidate
        else:
            domain_roots = [
                ("sign in", "Sign In"),
                ("signin", "Sign In"),
                ("login", "Sign In"),
                ("checkout", "Checkout"),
                ("payment", "Payments"),
                ("file upload", "File Upload"),
                ("upload", "File Upload"),
                ("product search", "Product Search"),
                ("search", "Product Search"),
                ("admin", "Admin Role Management"),
                ("role management", "Admin Role Management"),
                ("order creation", "API Order Creation"),
                ("order", "API Order Creation"),
                ("booking", "Booking"),
                ("refund", "Refunds"),
                ("cart", "Cart"),
            ]
            for needle, name in domain_roots:
                if needle in lower:
                    root = name
                    break

        branches: list[dict[str, Any]] = []
        seen: set[str] = set()
        auth_patterns = [
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
        generic_patterns = [
            ("guest", "Guest Checkout", False),
            ("registered", "Registered User", False),
            ("payment", "Payment", False),
            ("address", "Address Validation", False),
            ("valid file", "Valid File", False),
            ("unsupported", "Unsupported Type", True),
            ("oversized", "Oversized File", True),
            ("interrupted", "Upload Interrupted", True),
            ("filter", "Search Filters", False),
            ("permission", "Permission Check", False),
            ("role", "Role Assignment", False),
            ("schema", "Schema Validation", False),
            ("api", "API Contract", False),
            ("inventory", "Inventory Service", False),
            ("timeout", "Timeout", True),
            ("failure", "Failure Path", True),
            ("retry", "Retry", False),
            ("cancel", "Cancellation", False),
        ]

        for needle, name, failure in auth_patterns + generic_patterns:
            if needle in lower and name not in seen:
                seen.add(name)
                branches.append(
                    {
                        "name": name,
                        "type": "FailurePath" if failure else "SubFeature",
                        "is_failure_path": failure,
                        "inferred": True,
                        "children": [],
                    }
                )

        list_match = re.search(
            r"(?:supports|includes|with|branches?)\s+(.+?)(?:\.|$)",
            body,
            re.I | re.S,
        )
        if list_match:
            chunk = list_match.group(1)
            parts = re.split(r",|\band\b|\bor\b", chunk, flags=re.I)
            for part in parts:
                name = re.sub(r"\s+", " ", part).strip(" .;:-")
                if len(name) < 2 or len(name) > 60:
                    continue
                if name.lower() in {"the", "a", "an", "to", "for"}:
                    continue
                title = name[0].upper() + name[1:]
                if title not in seen:
                    seen.add(title)
                    branches.append(
                        {
                            "name": title,
                            "type": "SubFeature",
                            "is_failure_path": False,
                            "inferred": True,
                            "children": [],
                        }
                    )

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
            branches = [
                b
                for b in branches
                if b["name"] not in nested_names and b["name"] != "Email + Password"
            ]
            branches.insert(0, email)

        return {
            "root": root,
            "description": "Inferred from natural language (demo mode).",
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
