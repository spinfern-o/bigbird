"""SmartRoute AI: decide whether an edit stays local or needs generative GPU work.

The router is intentionally separate from image generation.  A small local LLM may
classify the user's request, but the actual pixels are still produced by deterministic
PhotoForge tools or by the authenticated NVIDIA cloud backend.

This module has no mandatory new dependency.  For hackathon/demo builds, set
PHOTOFORGE_ROUTER_MODEL to a commercially licensed GGUF model and install
llama-cpp-python.  If that model is unavailable, the deterministic fallback keeps the
feature usable and testable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable

LOCAL_EDIT = "LOCAL_EDIT"
GPU_GENERATE = "GPU_GENERATE"
ASK_CLARIFY = "ASK_CLARIFY"
VALID_ROUTES = {LOCAL_EDIT, GPU_GENERATE, ASK_CLARIFY}


@dataclass(frozen=True)
class RouterContext:
    """Small, privacy-preserving facts used for routing.

    The router does not need image pixels.  It only receives prompt text plus coarse
    editing context, which makes local classification cheap and keeps routing separate
    from generation.
    """

    has_selection: bool = False
    selection_fraction: float = 0.0
    transparent_fraction: float = 0.0


@dataclass(frozen=True)
class RouteDecision:
    route: str
    operation: str
    reason: str
    confidence: float
    local_adjustments: dict[str, int] = field(default_factory=dict)
    source: str = "fallback"

    @property
    def uses_gpu(self) -> bool:
        return self.route == GPU_GENERATE

    @property
    def badge(self) -> str:
        if self.route == LOCAL_EDIT:
            return "LOCAL - fast + private"
        if self.route == GPU_GENERATE:
            return "GPU - generative / precision"
        return "CLARIFY - needs one detail"


def _clamp_confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _extract_json(text: str) -> dict:
    """Parse a model response even if it wrapped the object in prose/fences."""
    text = (text or "").strip()
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _normalise_llm_decision(payload: dict) -> RouteDecision | None:
    route = str(payload.get("route", "")).strip().upper()
    if route not in VALID_ROUTES:
        return None

    adjustments = payload.get("local_adjustments") or {}
    if not isinstance(adjustments, dict):
        adjustments = {}
    clean_adjustments = {}
    for key, value in adjustments.items():
        try:
            clean_adjustments[str(key)] = int(value)
        except (TypeError, ValueError):
            continue

    reason = str(payload.get("reason") or "").strip()
    if not reason:
        reason = (
            "This can stay on your computer."
            if route == LOCAL_EDIT
            else "This edit needs generated pixels."
            if route == GPU_GENERATE
            else "I need one more detail before editing."
        )

    return RouteDecision(
        route=route,
        operation=str(payload.get("operation") or "edit").strip() or "edit",
        reason=reason,
        confidence=_clamp_confidence(payload.get("confidence", 0.7)),
        local_adjustments=clean_adjustments,
        source="local_llm",
    )


def build_llm_prompt(prompt: str, context: RouterContext) -> str:
    """Prompt for a tiny local routing model; output is deliberately constrained."""
    return f"""You are PhotoForge SmartRoute. Route a photo-editing request.

Return ONLY one JSON object with these keys:
  route: LOCAL_EDIT | GPU_GENERATE | ASK_CLARIFY
  operation: short_snake_case_intent
  reason: one short user-facing sentence, maximum 12 words
  confidence: number from 0 to 1
  local_adjustments: object of PhotoForge slider deltas, or {{}}

LOCAL_EDIT only when existing deterministic controls can perform the request:
exposure, contrast, highlights, shadows, whites, blacks, temperature, tint,
vibrance, saturation, clarity, dehaze, fade, vignette, grain, sharpness.

GPU_GENERATE when the request needs new semantic pixels or reconstruction:
add/remove/replace objects, replace backgrounds/skies, fill missing/transparent
areas, scene changes, weather changes, or detailed generative transformation.

ASK_CLARIFY only if the request does not say what should change.

Context:
has_selection={context.has_selection}
selection_fraction={context.selection_fraction:.4f}
transparent_fraction={context.transparent_fraction:.4f}

User request: {json.dumps(prompt)}
"""


class LlamaCppRouter:
    """Optional local GGUF router using llama-cpp-python.

    Loading is lazy so normal PhotoForge installs keep working without the optional
    router model.  The selected model must be commercially licensed before shipping.
    """

    def __init__(self, model_path: str | None = None):
        self.model_path = model_path or os.environ.get("PHOTOFORGE_ROUTER_MODEL", "")
        self._model = None

    @property
    def available(self) -> bool:
        return bool(self.model_path and os.path.isfile(self.model_path))

    def _load(self):
        if self._model is not None:
            return self._model
        if not self.available:
            raise RuntimeError("No local SmartRoute model is configured.")
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "The optional SmartRoute model needs llama-cpp-python."
            ) from exc
        self._model = Llama(
            model_path=self.model_path,
            n_ctx=2048,
            verbose=False,
        )
        return self._model

    def classify(self, prompt: str, context: RouterContext) -> str:
        model = self._load()
        result = model.create_completion(
            prompt=build_llm_prompt(prompt, context),
            max_tokens=180,
            temperature=0,
            stop=["\n\n"],
        )
        return result["choices"][0]["text"]


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

_GENERATIVE_PATTERNS = (
    r"\badd\b",
    r"\binsert\b",
    r"\bremove\b.*\b(person|people|object|car|sign|tree|building|background)\b",
    r"\breplace\b",
    r"\bswap\b",
    r"\bchange (the )?(sky|background|scene|weather)\b",
    r"\bfill\b.*\b(gap|hole|area|background|missing|transparent)\b",
    r"\breconstruct\b",
    r"\bgenerate\b",
    r"\bmake .*\b(sunset|snow|snowy|rain|rainy|night|day|fog|foggy)\b",
    r"\bturn .* into\b",
)

_LOCAL_RULES: tuple[tuple[tuple[str, ...], str, int, str], ...] = (
    (("brighter", "brighten", "increase exposure", "more exposure"),
     "exposure", 35, "brightness"),
    (("darker", "darken", "decrease exposure", "less exposure"),
     "exposure", -35, "brightness"),
    (("warmer", "warm it", "more warm", "golden tone"),
     "temperature", 30, "temperature"),
    (("cooler", "cool it", "more cool"),
     "temperature", -30, "temperature"),
    (("more contrast", "increase contrast", "punchier"),
     "contrast", 25, "contrast"),
    (("less contrast", "reduce contrast", "softer contrast"),
     "contrast", -25, "contrast"),
    (("more saturated", "increase saturation", "more saturation"),
     "saturation", 25, "saturation"),
    (("less saturated", "desaturate", "reduce saturation"),
     "saturation", -25, "saturation"),
    (("black and white", "black & white", "grayscale", "greyscale"),
     "saturation", -100, "black_and_white"),
    (("more vibrant", "increase vibrance", "boost vibrance"),
     "vibrance", 30, "vibrance"),
    (("recover highlights", "lower highlights", "reduce highlights"),
     "highlights", -35, "highlights"),
    (("lift shadows", "raise shadows", "brighten shadows"),
     "shadows", 35, "shadows"),
    (("more clarity", "increase clarity"),
     "clarity", 25, "clarity"),
    (("dehaze", "remove haze", "less haze"),
     "dehaze", 30, "dehaze"),
    (("sharper", "sharpen", "more sharp"),
     "sharpness", 30, "sharpness"),
)


def _fallback_route(prompt: str, context: RouterContext) -> RouteDecision:
    text = " ".join(prompt.lower().split())
    if len(text) < 3:
        return RouteDecision(
            ASK_CLARIFY,
            "clarify",
            "Tell me what you want to change.",
            0.99,
            source="fallback",
        )

    # A transparent A5 gap strongly implies reconstruction if the user mentions filling it.
    if context.transparent_fraction > 0.0005 and any(
        word in text for word in ("fill", "fix the gap", "removed area", "hole")
    ):
        return RouteDecision(
            GPU_GENERATE,
            "fill_removed_area",
            "Missing pixels need generative reconstruction.",
            0.98,
            source="fallback",
        )

    for pattern in _GENERATIVE_PATTERNS:
        if re.search(pattern, text):
            return RouteDecision(
                GPU_GENERATE,
                "generative_edit",
                "This request needs new semantic pixels.",
                0.94,
                source="fallback",
            )

    adjustments: dict[str, int] = {}
    operations: list[str] = []
    for phrases, key, value, operation in _LOCAL_RULES:
        if any(phrase in text for phrase in phrases):
            adjustments[key] = value
            operations.append(operation)

    if adjustments:
        return RouteDecision(
            LOCAL_EDIT,
            "+".join(dict.fromkeys(operations)),
            "Existing local controls can make this edit.",
            0.93,
            adjustments,
            source="fallback",
        )

    # A clear editing verb with no deterministic representation is safer on the
    # generative path than pretending a slider can reproduce it.
    if re.search(r"\b(make|change|edit|transform|turn|fix)\b", text):
        return RouteDecision(
            GPU_GENERATE,
            "generative_edit",
            "Local controls cannot represent this request precisely.",
            0.72,
            source="fallback",
        )

    return RouteDecision(
        ASK_CLARIFY,
        "clarify",
        "Tell me what you want to change.",
        0.75,
        source="fallback",
    )


class SmartEditRouter:
    """Local-first router with an optional LLM and deterministic safety fallback."""

    def __init__(
        self,
        llm: LlamaCppRouter | None = None,
        classifier: Callable[[str, RouterContext], str] | None = None,
    ):
        self.llm = llm or LlamaCppRouter()
        self.classifier = classifier

    def route(self, prompt: str, context: RouterContext | None = None) -> RouteDecision:
        context = context or RouterContext()
        prompt = (prompt or "").strip()

        # Tests and future bundled routers can inject a classifier without depending on
        # llama-cpp-python.
        classify = self.classifier
        if classify is None and self.llm.available:
            classify = self.llm.classify

        if classify is not None:
            try:
                payload = _extract_json(classify(prompt, context))
                decision = _normalise_llm_decision(payload)
                if decision is not None:
                    # Never allow an LLM to claim a missing-pixel fill is a cheap local
                    # slider edit.  Routing policy remains under application control.
                    if (
                        context.transparent_fraction > 0.0005
                        and decision.route == LOCAL_EDIT
                        and any(w in prompt.lower() for w in ("fill", "gap", "hole"))
                    ):
                        return _fallback_route(prompt, context)
                    return decision
            except Exception:
                # Routing must never make editing unavailable.  A broken/missing local
                # classifier simply falls back to explicit application rules.
                pass

        return _fallback_route(prompt, context)
