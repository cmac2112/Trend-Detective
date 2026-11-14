"""Plain-language explanation of a driver analysis, written by Claude.

The statistics in drivers.py are the evidence; Claude's job is to explain them to a
high-school / college audience, keep cause and correlation apart, and suggest what
else might be going on (clearly labeled as not measured).

Needs an Anthropic API key in the ANTHROPIC_API_KEY environment variable (the API
server loads it from TrendApi/.env). Without one, explain() returns
{"available": False, "reason": ...} and everything else keeps working.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Literal

from pydantic import BaseModel, Field

MODEL = "claude-haiku-5-5"  # fast and inexpensive; the evidence is already computed
_CACHE_MAX = 256
_cache: OrderedDict[str, dict] = OrderedDict()  # identical evidence -> reuse the explanation
_cache_lock = threading.Lock()

SYSTEM_PROMPT = """You are the science explainer inside Trend Detective, a web app where high-school and \
college students (and curious members of the public) draw a region on a map and test whether a NASA \
Earth-science variable is changing there.

You receive the results of a statistical cause analysis as JSON: the target variable's trend, and for \
each candidate driver its own trend, its correlation with the target (after removing the seasonal \
cycle, with p-values adjusted for autocorrelation), how much of the target's trend a regression \
attributes to it, a machine-learning importance score, an evidence label, and a short note on the \
known physical link between the two variables, including which way the effect usually runs.

Write an explanation that:
- is grounded in the numbers you were given; never invent statistics or data that isn't there
- treats associations as possible causes, not proof, and uses each physical link to say which \
direction the effect most plausibly runs (e.g. rain drives soil moisture, not the reverse)
- uses the region's location, climate numbers and name to suggest other well-known factors that \
this data cannot measure (land-use change, deforestation, sea-ice loss, irrigation, urbanization, \
large-scale climate patterns), clearly separated from what the data shows
- says honestly when the evidence is weak, when the target trend itself is not significant, or when \
the machine-learning model has no predictive skill
- is written for a 16-year-old: short sentences, no jargon without a quick definition, numbers with \
units, about 150-250 words across the summary and causes."""


class Cause(BaseModel):
    cause: str = Field(description="Short name of the possible cause, e.g. 'Drying soil'")
    shown_by_data: bool = Field(description="True if supported by the measured variables, False if it is outside knowledge")
    explanation: str = Field(description="1-3 sentences: the mechanism and the evidence (cite the numbers)")
    confidence: Literal["strong", "moderate", "weak", "speculative"]


class Explanation(BaseModel):
    headline: str = Field(description="One sentence answering 'why is it changing?'")
    summary: str = Field(description="2-4 sentence plain-language overview")
    likely_causes: list[Cause] = Field(description="Most to least likely, 1-4 items")
    other_possible_factors: list[str] = Field(description="Factors the data can't measure that may matter here")
    caveats: list[str] = Field(description="The 2-3 most important limits of this analysis, plainly worded")
    investigate_next: list[str] = Field(description="1-3 concrete next steps a student could try in this app")


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def evidence_payload(attribution: dict, region_name: str | None = None) -> dict:
    """The compact, numbers-only view of a driver analysis that Claude sees."""
    t = attribution["target"]["stats"]
    lin = t["linear"]

    def rnd(v, n=3):
        return None if v is None else round(v, n)

    return {
        "region_name": region_name,
        "region": attribution["region_context"],
        "period": {"start": attribution["start"], "end": attribution["end"]},
        "target": {
            "variable": attribution["variable"]["name"],
            "units": attribution["variable"]["units"],
            "definition": attribution["variable"]["definition"],
            "slope_per_decade": rnd(lin["slope_per_decade"]),
            "ci95_per_decade": [rnd(v) for v in lin["ci95_per_decade"]],
            "total_change": rnd(lin["total_change"]),
            "p_value": rnd(lin["p_value"], 4),
            "mann_kendall_p": rnd(t["mann_kendall"]["p_value"], 4),
            "significant": t["significant"],
            "verdict": t["verdict"],
        },
        "drivers": [
            {
                "rank": d["rank"],
                "variable": d["name"],
                "units": d["units"],
                "own_trend_per_decade": rnd(d["trend"]["slope_per_decade"]),
                "own_trend_significant": d["trend"]["significant"],
                "correlation_r": rnd(d["correlation"]["r"], 2),
                "correlation_lag_months": d["correlation"]["lag_months"],
                "correlation_p": rnd(d["correlation"]["p_value"], 4),
                "share_of_target_trend": rnd(d["regression"]["share_of_target_trend"], 2),
                "ml_importance_share": rnd(d["ml_importance_share"], 2),
                "evidence": d["evidence"],
                "physical_link": d["physical_link"],
            }
            for d in attribution["drivers"]
        ],
        "models": attribution["models"],
        "caveats": attribution["caveats"],
    }


def explain(attribution: dict, region_name: str | None = None) -> dict:
    """Ask Claude to explain a driver analysis. Never raises: failures come back as
    {"available": False, "reason": ...} so the statistics are still shown."""
    if not has_api_key():
        return {"available": False,
                "reason": "AI explanation is off: add ANTHROPIC_API_KEY to TrendApi/.env and restart the API."}

    payload = evidence_payload(attribution, region_name)
    key = hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return {**copy.deepcopy(_cache[key]), "cached": True}

    import anthropic

    client = anthropic.Anthropic(timeout=120.0, max_retries=2)
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": "Explain why this variable is changing in this region.\n\n<analysis>\n"
                           + json.dumps(payload, indent=1, default=str) + "\n</analysis>",
            }],
            output_format=Explanation,
        )
    except anthropic.AuthenticationError:
        return {"available": False, "reason": "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in TrendApi/.env."}
    except anthropic.PermissionDeniedError:
        return {"available": False, "reason": "The Anthropic API key doesn't have access to this model."}
    except anthropic.RateLimitError:
        return {"available": False, "reason": "The AI service is busy (rate limited). Try again in a minute."}
    except anthropic.APIStatusError as e:
        return {"available": False, "reason": f"The AI service returned an error ({e.status_code})."}
    except anthropic.APIConnectionError:
        return {"available": False, "reason": "Couldn't reach the AI service. Check the internet connection."}

    if response.stop_reason == "refusal" or response.parsed_output is None:
        return {"available": False, "reason": "The AI model declined or returned no usable explanation."}

    result = {
        "available": True,
        "model": response.model,
        **response.parsed_output.model_dump(),
    }
    with _cache_lock:
        _cache[key] = copy.deepcopy(result)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return {**result, "cached": False}
