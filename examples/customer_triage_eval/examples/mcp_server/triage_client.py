"""Gmail triage — MCP client demo (end-to-end).

Spawns server.py over stdio, discovers its tools, pulls unread mail, and asks
Claude to triage each one: auto-reply with a draft, or escalate to a human.
Mirrors the decision the main LangGraph agent makes — but here the mailbox I/O
crosses an MCP boundary instead of being an in-process function call.

Safe by default: prints drafts without sending. Pass --send to actually send
replies (and mark them read) through the MCP server.

    python triage_client.py            # dry run — print drafts only
    python triage_client.py --send     # actually send + mark read
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "claude-haiku-4-5-20251001"  # matches the main triage agent
_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_HERE, ".env"))  # picks up ANTHROPIC_API_KEY


def _tool_json(result):
    """Return a tool call's value as Python data.

    Prefer structuredContent (the full, typed return); FastMCP wraps a non-dict
    return like a list as {"result": [...]}, so unwrap that. Fall back to the
    first text block, which for a list only carries the first item.
    """
    sc = getattr(result, "structuredContent", None)
    if isinstance(sc, dict):
        return sc["result"] if set(sc) == {"result"} else sc
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


def triage(anthropic: Anthropic, email: dict) -> dict:
    """Ask Claude to decide reply-vs-escalate and draft a reply if replying."""
    system = (
        "You are a customer-support triage agent. Read the email and decide "
        "whether it can be safely auto-answered. Respond with ONLY a JSON object: "
        '{"action": "reply" | "escalate", "draft": "<reply text, or empty>"}. '
        "Escalate anything ambiguous, angry, legal/financial, or that you cannot "
        "answer confidently from the email alone. Keep drafts short and warm."
    )
    user = f"From: {email['from']}\nSubject: {email['subject']}\n\n{email['body']}"
    msg = anthropic.messages.create(
        model=MODEL, max_tokens=512, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text.strip()
    try:  # tolerate stray prose around the JSON
        return json.loads(text[text.index("{"): text.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return {"action": "escalate", "draft": ""}


async def main(send: bool, limit: int) -> None:
    anthropic = Anthropic()
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(_HERE, "server.py")])

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Connected to MCP server. Tools:", [t.name for t in tools.tools], "\n")

            unread = _tool_json(await session.call_tool("list_unread_emails", {"max_results": limit})) or []
            print(f"{len(unread)} unread email(s) to triage.\n")

            for row in unread:
                full = _tool_json(await session.call_tool("get_email", {"message_id": row["id"]}))
                decision = triage(anthropic, full)

                print("=" * 70)
                print(f"From   : {full['from']}")
                print(f"Subject: {full['subject']}")
                print(f"Action : {decision['action']}")

                if decision["action"] == "reply" and decision.get("draft"):
                    print(f"Draft  :\n{decision['draft']}\n")
                    if send:
                        await session.call_tool("send_reply", {"message_id": row["id"], "body": decision["draft"]})
                        await session.call_tool("mark_as_read", {"message_id": row["id"]})
                        print(">> Sent and marked read.")
                    else:
                        print(">> DRY RUN — pass --send to actually reply.")
                else:
                    print(">> Escalated to human review (left unread).")
            print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="MCP Gmail triage demo")
    ap.add_argument("--send", action="store_true", help="actually send replies (default: dry run)")
    ap.add_argument("--limit", type=int, default=5, help="max unread emails to triage")
    args = ap.parse_args()
    asyncio.run(main(args.send, args.limit))
