"""Gmail triage — MCP server.

Exposes four Gmail operations as MCP tools over stdio, so any MCP client
(Claude Desktop, the triage_client.py in this folder, or a LangGraph agent
wired up as a client) can read and act on a mailbox.

This is the same idea as a Sema4 `@action` or a LangChain `@tool`: a typed
Python function with a clear docstring that an agent reasons about and calls.
The MCP SDK turns each one into a discoverable, callable tool for free.

Run standalone (does the OAuth consent flow on first call):
    python server.py            # then talk to it from an MCP client
"""

from __future__ import annotations

import os
import sys

# Make this folder importable no matter where the MCP client launches us from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gmail_service as gmail  # noqa: E402
from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("gmail-triage")


@mcp.tool()
def list_unread_emails(max_results: int = 10) -> list[dict]:
    """List unread emails in the inbox. Returns each message's id, thread_id,
    sender, subject, and a short snippet. Call this first to see what needs
    triaging, then use get_email to read the full body of any one of them."""
    return gmail.list_unread(gmail.get_service(), max_results)


@mcp.tool()
def get_email(message_id: str) -> dict:
    """Fetch the full sender, subject, and plain-text body of one email by its
    message_id (as returned by list_unread_emails). Use this to read a ticket
    before deciding whether to reply or escalate it."""
    return gmail.get_message(gmail.get_service(), message_id)


@mcp.tool()
def send_reply(message_id: str, body: str) -> dict:
    """Send a plain-text reply to the email with this message_id. The reply is
    kept in the original thread and addressed to the original sender. Only send
    when you are confident in the answer; otherwise leave it for a human."""
    return gmail.send_reply(gmail.get_service(), message_id, body)


@mcp.tool()
def mark_as_read(message_id: str) -> dict:
    """Mark the email with this message_id as read (removes the UNREAD label).
    Use after you have handled a message so it is not triaged again."""
    return gmail.mark_as_read(gmail.get_service(), message_id)


if __name__ == "__main__":
    mcp.run()  # stdio transport by default
