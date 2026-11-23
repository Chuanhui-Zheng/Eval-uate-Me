# Gmail Triage — MCP Server

A small [Model Context Protocol](https://modelcontextprotocol.io) server that exposes a Gmail inbox as agent tools, plus a client that triages unread mail end-to-end. It's the companion to the main [customer-triage agent](../../README.md): the agent decides *reply vs. escalate*; this shows the same decision reaching a **real mailbox** across an MCP boundary instead of an in-process function call.

Four tools, over stdio:

| Tool | What it does |
|------|--------------|
| `list_unread_emails` | List unread inbox messages (id, sender, subject, snippet) |
| `get_email` | Read one message's full plain-text body |
| `send_reply` | Send a threaded plain-text reply to the original sender |
| `mark_as_read` | Remove the `UNREAD` label after handling |

Each tool is a typed Python function with a docstring the agent reasons over — the same shape as a LangChain `@tool` or a Sema4 `@action`. The MCP SDK turns each into a discoverable, callable tool automatically.

## Setup

Uses a throwaway Gmail account so nothing touches a real inbox. **Never commit `credentials.json` or `token.json`** — both are git-ignored.

1. **Install deps** (reuse the repo's venv, or make one here):
   ```bash
   pip install -r requirements.txt
   ```
2. **Google Cloud project** — reuse an existing one or make a new one. Enable the **Gmail API**, then create an **OAuth client ID** of type **Desktop app** and download it as `credentials.json` into this folder. Under the OAuth consent screen, add your test Gmail address as a **test user**.
3. **Anthropic key** for the triage client:
   ```bash
   cp .env.example .env   # then paste your key
   ```
4. **First run does the consent flow** — a browser opens, you approve, and `token.json` is written next to the code:
   ```bash
   python server.py       # authorizes, then waits as an MCP server (Ctrl-C to stop)
   ```
   > Scopes are `gmail.modify` + `gmail.send`. If you previously authorized this account for read-only, delete `token.json` and re-run so Google re-prompts for send.

## Run it

**As a standalone triage loop** (spawns the server for you):
```bash
python triage_client.py          # dry run — prints drafts, sends nothing
python triage_client.py --send   # actually reply + mark read
```

**From Claude Desktop** — copy `claude_desktop_config.example.json` into your Claude Desktop config (`claude_desktop_config.json`), replace the two absolute paths, restart Claude Desktop, and ask: *"Check my unread emails and draft replies to the ones you can answer."*

## How it maps back

- **To the main agent** — the LangGraph graph classifies, retrieves, drafts, and gates on confidence. Point its final step at `send_reply` (as an MCP client) and the prototype becomes something that acts on a live mailbox.
- **To Sema4 Actions** — Sema4's Action Server auto-generates an MCP endpoint from typed `@action` functions. Understanding this server from the inside is understanding what that platform does under the hood: same typed-function-plus-docstring contract, same MCP surface.
