"""
Tony's Causal Reasoning Engine.

The difference between answering questions and understanding life.

Standard AI: "What should I do about X?"
             → "Here are some options..."

Tony with causal reasoning:
             → Maps the actual cause-effect chains
             → Identifies what's driving the problem vs symptoms
             → Predicts second and third-order effects of each option
             → Recommends based on Matthew's specific situation

Used for:
- Financial decisions (if I do X, what happens to Y and Z?)
- Legal strategy (what happens if I file FOS vs wait?)
- Life decisions (implications of career changes, financial choices)
- Goal planning (what's actually blocking this goal?)

This is what makes Tony feel like someone who genuinely thinks
rather than a search engine with a nice interface.
"""
import os
import json
from typing import Dict, List, Optional
from app.core.model_router import gemini, gemini_json


async def causal_analysis(
    situation: str,
    options: List[str] = None,
    matthew_context: str = ""
) -> Dict:
    """
    Tony maps cause-effect chains for a situation and predicts outcomes.
    """
    options_text = ""
    if options:
        options_text = f"\nOptions being considered:\n" + "\n".join(f"- {o}" for o in options)

    prompt = f"""You are Tony's causal reasoning engine. Analyse this situation for Matthew.

Situation: {situation}
{options_text}

Matthew's context: {matthew_context[:400] if matthew_context else 'Working night shifts, building Nova, dealing with Western Circle CCJ, wife Georgina, daughters Amelia and Margot'}

Map the causal chains:

1. ROOT CAUSES: What is actually driving this situation? (not symptoms)
2. IMMEDIATE EFFECTS: What happens right now from each option?
3. SECOND-ORDER EFFECTS: What happens 1-3 months later?
4. THIRD-ORDER EFFECTS: What happens 6-12 months later?
5. RISKS: What could go wrong that Matthew isn't considering?
6. HIDDEN OPPORTUNITIES: What does this situation make possible?
7. RECOMMENDATION: Given Matthew's specific situation, what is the best path?

Be specific to Matthew's actual life. Not generic advice.

Respond in JSON:
{{
    "root_causes": ["what's actually driving this"],
    "option_analysis": [
        {{
            "option": "option name",
            "immediate": "what happens right away",
            "medium_term": "1-3 months",
            "long_term": "6-12 months",
            "risk": "main risk",
            "probability_success": "high/medium/low"
        }}
    ],
    "hidden_opportunities": ["things this situation makes possible"],
    "recommendation": "Tony's specific recommendation for Matthew",
    "reasoning": "why this recommendation fits Matthew's situation specifically"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=1500) or {}


async def predict_outcome(action: str, current_state: str) -> Dict:
    """
    If Matthew does X, what will likely happen?
    Tony models the likely trajectory.
    """
    prompt = f"""Tony is predicting the outcome of an action for Matthew.

Action Matthew is considering: {action}
Current situation: {current_state[:500]}
Matthew's context: Night shift care worker in Rotherham, building AI app, CCJ dispute, wife and 2 young daughters

Model what likely happens:

Timeline predictions (be realistic, not optimistic):
- This week:
- This month:
- In 3 months:
- In 6 months:
- Risk of this going wrong:
- What would make this succeed vs fail?

Respond in JSON:
{{
    "this_week": "what likely happens",
    "this_month": "what likely happens",
    "three_months": "what likely happens",
    "six_months": "what likely happens",
    "success_probability": "percentage and reasoning",
    "key_risks": ["specific risks"],
    "success_factors": ["what needs to be true for this to work"],
    "tony_verdict": "Tony's honest one-sentence verdict"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=1024) or {}


async def identify_goal_blockers(goal: str, attempts: str = "") -> Dict:
    """
    What is actually blocking this goal?
    Tony digs into root causes, not surface symptoms.
    """
    prompt = f"""Tony is identifying what's actually blocking Matthew from achieving a goal.

Goal: {goal}
What Matthew has tried: {attempts or 'Not specified'}
Context: Matthew works nights, has limited time, building app from his phone, dealing with legal/financial stress

Identify the ACTUAL blockers (not symptoms):

Blockers can be:
- Resource (time, money, skills, tools)
- Psychological (fear, doubt, clarity)
- External (people, systems, circumstances)
- Sequential (something else needs to happen first)
- Informational (doesn't know something critical)

For each blocker:
- How severe is it? (1-10)
- Is it within Matthew's control?
- What specifically would remove it?

Respond in JSON:
{{
    "primary_blocker": "the single most important thing blocking this",
    "blockers": [
        {{
            "type": "resource/psychological/external/sequential/informational",
            "description": "specific blocker",
            "severity": 1-10,
            "in_matthew_control": true/false,
            "how_to_remove": "specific action"
        }}
    ],
    "critical_path": "what must happen first before anything else",
    "quick_win": "something Matthew could do in the next 24 hours to make progress",
    "tony_assessment": "Tony's honest assessment of this goal's achievability"
}}"""

    return await gemini_json(prompt, task="reasoning", max_tokens=1024) or {}
