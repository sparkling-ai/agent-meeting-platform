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


# ── Existing functions ───────────────────────────────────────────────────────

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


# ── Moderator-specific LLM functions ────────────────────────────────────────

async def moderator_intervene(context: str, trigger: str) -> str:
    """Generate an intervention message from the moderator."""
    prompt = f"""You are a professional meeting moderator. An issue has been detected: {trigger}.

Recent discussion context:
{context[-2000:]}

Write a brief, professional intervention message (2-3 sentences) to address this issue.
Be firm but respectful. If relevant, suggest a specific action (vote, summarize, move on)."""
    return await _call_llm(prompt, system="You are a professional meeting moderator. Be concise.", max_tokens=200)


async def moderator_summarize(messages: str, topic: str) -> str:
    """Generate a discussion summary for a specific topic."""
    prompt = f"""Summarize this discussion about "{topic}" in 3-5 bullet points.
Focus on: key positions, areas of agreement/disagreement, and unresolved questions.

Discussion:
{messages[-3000:]}"""
    return await _call_llm(prompt, system="You are a professional meeting moderator writing a summary.", max_tokens=400)


async def moderator_check_drift(message: str, agenda_item: str) -> dict:
    """Check if a message is on-topic relative to the current agenda item."""
    prompt = f"""Is this message on-topic for the current agenda item?

Agenda item: "{agenda_item}"
Message: "{message}"

Respond with ONLY a JSON object: {{"on_topic": true/false, "reason": "brief explanation"}}"""
    result = await _call_llm(prompt, system="You are a meeting analyst. Respond only with valid JSON.", max_tokens=100)
    try:
        start = result.index("{")
        end = result.rindex("}") + 1
        return json.loads(result[start:end])
    except (json.JSONDecodeError, ValueError):
        return {"on_topic": True, "reason": "Could not analyze"}


async def moderator_extract_actions(decisions: str, messages: str) -> list[str]:
    """Extract action items from decisions and discussion."""
    prompt = f"""Given these decisions and the discussion, list concrete action items (one per line).
Each should start with a verb and include who should do it.

Decisions:
{decisions}

Discussion context:
{messages[-2000:]}"""
    result = await _call_llm(prompt, system="You are a project manager extracting action items.", max_tokens=300)
    items = [line.strip().lstrip("-•*0-9. ") for line in result.split("\n") if line.strip()]
    return items[:10]


async def moderator_minutes(room_id: str, decisions: str, actions: str) -> str:
    """Generate final meeting minutes."""
    prompt = f"""Generate professional meeting minutes.

Decisions made:
{decisions}

Discussion summary:
{actions[-2000:]}

Write clear, structured meeting minutes with:
1. Executive Summary (2-3 sentences)
2. Key Decisions
3. Action Items
4. Open Questions / Parking Lot"""
    return await _call_llm(prompt, system="You are a professional meeting secretary.", max_tokens=600)


async def moderator_steel_man(arguments: list[str]) -> str:
    """Steel-man opposing arguments for conflict resolution."""
    args_text = "\n".join(f"Position {i+1}: {a}" for i, a in enumerate(arguments))
    prompt = f"""Two sides are in disagreement. Steel-man (represent in strongest form) each position,
then find common ground or a third option.

{args_text}

Write:
1. Strongest version of Position 1
2. Strongest version of Position 2
3. Common ground between both
4. Suggested compromise or third option"""
    return await _call_llm(prompt, system="You are a skilled mediator.", max_tokens=400)
