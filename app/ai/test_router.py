"""Regression tests for SmartRoute AI.

Run from the repository root:
    python app/ai/test_router.py

No model download, GPU, network, or account is required.
"""

from app.ai.router import (
    ASK_CLARIFY,
    GPU_GENERATE,
    LOCAL_EDIT,
    RouterContext,
    SmartEditRouter,
)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    print(f"[PASS] {name}")


def main():
    router = SmartEditRouter(classifier=None)

    d = router.route("make this warmer")
    check("warmth stays local", d.route == LOCAL_EDIT)
    check("warmth maps to temperature", d.local_adjustments.get("temperature") == 30)
    check("local badge is concise", d.badge.startswith("LOCAL"))

    d = router.route("make the photo brighter and more vibrant")
    check("multiple deterministic edits stay local", d.route == LOCAL_EDIT)
    check("brightness mapped", d.local_adjustments.get("exposure") == 35)
    check("vibrance mapped", d.local_adjustments.get("vibrance") == 30)

    d = router.route("replace the sky with a dramatic sunset")
    check("semantic replacement uses GPU", d.route == GPU_GENERATE)

    d = router.route("add snow to the street")
    check("content insertion uses GPU", d.route == GPU_GENERATE)

    d = router.route(
        "make this warmer",
        RouterContext(has_selection=True, selection_fraction=0.2),
    )
    check("selection-constrained edit uses precision GPU route", d.route == GPU_GENERATE)

    d = router.route(
        "fill the removed area",
        RouterContext(transparent_fraction=0.12),
    )
    check("A5 gap fill uses GPU", d.route == GPU_GENERATE)
    check("A5 gap gets explicit operation", d.operation == "fill_removed_area")

    d = router.route("")
    check("blank prompt asks for clarification", d.route == ASK_CLARIFY)

    def fake_local_llm(prompt, context):
        return """{
          "route": "LOCAL_EDIT",
          "operation": "contrast",
          "reason": "A local slider can do this.",
          "confidence": 0.91,
          "local_adjustments": {"contrast": 18}
        }"""

    llm_router = SmartEditRouter(classifier=fake_local_llm)
    d = llm_router.route("give it slightly more punch")
    check("injected LLM decision accepted", d.route == LOCAL_EDIT)
    check("LLM source recorded", d.source == "local_llm")
    check("LLM adjustment preserved", d.local_adjustments["contrast"] == 18)

    def unsafe_llm(prompt, context):
        return """{
          "route": "LOCAL_EDIT",
          "operation": "exposure",
          "reason": "Do it locally.",
          "confidence": 0.99,
          "local_adjustments": {"exposure": 10}
        }"""

    safe_router = SmartEditRouter(classifier=unsafe_llm)
    d = safe_router.route(
        "fill this gap",
        RouterContext(transparent_fraction=0.2),
    )
    check("policy overrides unsafe LLM gap route", d.route == GPU_GENERATE)

    print("All SmartRoute regression tests passed.")


if __name__ == "__main__":
    main()
