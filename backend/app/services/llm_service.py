"""LLM integration via LiteLLM for moderator intelligence."""

import json
import logging
import os

import litellm

from app.config import settings

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True


async def _call_llm(prompt: str, system: str = "", max_tokens: int = 500) -> str:
    """Call LLM via LiteLLM with the configured model."""
    api_key = settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("No OPENROUTER_API_KEY configured")

    model = settings.llm_model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            api_key=api_key,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        raise


async def generate_summary(room_context: str) -> str:
    """Generate a meeting summary from room context."""
    prompt = f"""Summarize the following meeting discussion in 2-4 bullet points.
Focus on key arguments, areas of agreement, and unresolved questions.

Discussion:
{room_context}"""
    return await _call_llm(prompt, system="You are a professional meeting moderator.", max_tokens=300)


async def extract_action_items(decision_context: str) -> list[str]:
    """Extract action items from a decision context."""
    prompt = f"""Given this meeting context and decision, list concrete action items (one per line).
Each item should start with a verb and be specific enough to assign.

Context:
{decision_context}"""
    result = await _call_llm(prompt, system="You are a project manager.", max_tokens=300)
    items = [line.strip().lstrip("-•*0-9. ") for line in result.split("\n") if line.strip()]
    return items[:10]


async def check_convergence(message_history: str) -> dict:
    """Check if the discussion is going in circles."""
    prompt = f"""Analyze this meeting discussion. Is it going in circles?
Respond with ONLY a JSON object: {{"converging": true/false, "reason": "brief explanation", "suggestion": "what to do next"}}

Discussion:
{message_history[-3000:]}"""
    result = await _call_llm(prompt, system="You are a meeting analyst. Respond only with valid JSON.", max_tokens=200)
    try:
        start = result.index("{")
        end = result.rindex("}") + 1
        return json.loads(result[start:end])
    except (json.JSONDecodeError, ValueError):
        return {"converging": False, "reason": "Could not analyze", "suggestion": "Continue discussion"}
