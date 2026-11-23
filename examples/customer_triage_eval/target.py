"""Adapter from the public LangGraph customer triage demo to eval_uate_me."""
from __future__ import annotations

import os
from typing import Any

from eval_uate_me import TargetOutput
import triage_agent as agent


class CustomerTriageTarget:
    def __init__(self, **_options: Any):
        from langchain_openai import ChatOpenAI
        from langchain.agents import create_agent

        model = ChatOpenAI(
            model=os.getenv("CUSTOMER_AGENT_MODEL", "openai/gpt-4o-mini"),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=os.environ["OPENROUTER_API_KEY"],
            temperature=0,
            max_tokens=512,
        )
        agent.MODEL = model
        agent._REACT_EXECUTOR = create_agent(
            model=model,
            tools=[agent.get_recent_system_status, agent.get_customer_recent_activity,
                   agent.search_knowledge_base],
            system_prompt=agent.REACT_SYSTEM_PROMPT,
        )
        self.graph = agent.build_graph()

    def run(self, case):
        state = {
            "ticket": case.input["ticket"],
            "category": None,
            "kb_hits": [],
            "draft_reply": None,
            "confidence": None,
            "final_decision": None,
        }
        trace = []
        final = dict(state)
        for update in self.graph.stream(state, stream_mode="updates"):
            for node, values in update.items():
                trace.append({"tool": f"node:{node}"})
                if isinstance(values, dict):
                    final.update(values)
        output = {
            "category": final.get("category"),
            "reply": final.get("draft_reply") or "",
            "confidence": final.get("confidence"),
            "decision": final.get("final_decision"),
            "kb_article_ids": [hit.get("id") for hit in final.get("kb_hits", [])],
        }
        return TargetOutput(output=output, trace=trace)


def run(case):
    """Entry point used by the built-in Python target adapter."""
    return CustomerTriageTarget().run(case)
