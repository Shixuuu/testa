"""DeepSeek AI client with function-calling for web search."""
from __future__ import annotations
import asyncio
import json
import os
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

SEARCH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web for current news, company background, market data, "
            "or any information the user asks about."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"}
            },
            "required": ["query"],
        },
    },
}


@dataclass
class ChatMessage:
    role: str    # "user" | "assistant" | "system" | "tool"
    content: str
    tool_calls: list | None = None
    tool_call_id: str | None = None
    name: str | None = None


def get_api_key() -> str:
    """Resolve DeepSeek API key from env var or config file."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    cfg = os.path.expanduser("~/.config/backtest_tui/config.toml")
    if os.path.exists(cfg):
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib  # type: ignore
            except ImportError:
                return ""
        with open(cfg, "rb") as f:
            data = tomllib.load(f)
        return data.get("ai", {}).get("deepseek_api_key", "")
    return ""


def build_context_block(state: dict) -> str:
    """Serialise all live app state into a structured text block for the AI."""
    lines = ["=== FUTURES BACKTEST TUI — LIVE CONTEXT ==="]

    lines += [
        f"Instrument   : {state.get('instrument', 'N/A')}",
        f"Account Size : ${state.get('initial_cash', 0):>12,.0f}",
        f"Bar          : {state.get('bar_index', 0):,} / {state.get('total_bars', 0):,}",
    ]

    cb = state.get("current_bar")
    if cb:
        lines.append(
            f"Current Bar  : O={cb.get('open',0):.2f} "
            f"H={cb.get('high',0):.2f} "
            f"L={cb.get('low',0):.2f} "
            f"C={cb.get('close',0):.2f}"
        )

    lines.append("\n--- ANALYTICS ---")
    for k, v in state.get("analytics", {}).items():
        lines.append(f"  {k:<22}: {v}")

    lines.append("\n--- PROP FIRM RULES ---")
    prop = state.get("prop", {})
    if prop:
        lines += [
            f"  Firm         : {prop.get('name', 'N/A')}",
            f"  Status       : {'BREACHED' if prop.get('is_breached') else 'OK'}",
            f"  Breach Rule  : {prop.get('breach_rule', '—')}",
            f"  Daily P&L    : ${prop.get('daily_pnl', 0):+,.2f} / ${prop.get('daily_limit', 0):,.2f}",
            f"  Trailing Flr : ${prop.get('trailing_floor', 0):,.2f}",
            f"  Peak Equity  : ${prop.get('peak_equity', 0):,.2f}",
            f"  Target Prog  : ${prop.get('net_pnl', 0):,.2f} / ${prop.get('profit_target', 0):,.2f}",
        ]

    mc = state.get("monte_carlo")
    if mc:
        lines += [
            "\n--- MONTE CARLO ---",
            f"  Method       : {mc.get('method', 'N/A')} | Paths: {mc.get('n_paths', 0):,}",
            f"  Median Final : ${mc.get('median_final', 0):,.2f}",
            f"  5th / 95th   : ${mc.get('pct5_final', 0):,.2f} / ${mc.get('pct95_final', 0):,.2f}",
            f"  Prob Ruin    : {mc.get('prob_ruin', 0)*100:.1f}%",
            f"  Prob Target  : {mc.get('prob_target', 0)*100:.1f}%",
        ]
        if mc.get("pass_rate") is not None:
            lines.append(f"  Pass Rate    : {mc['pass_rate']*100:.1f}%")

    trades = state.get("recent_trades", [])
    if trades:
        lines.append(f"\n--- RECENT TRADES (last {len(trades)}) ---")
        for t in trades:
            sign = "+" if t.get("pnl", 0) >= 0 else ""
            lines.append(
                f"  #{t.get('id','?'):>4} {t.get('direction','?'):<5} "
                f"{t.get('entry',0):.2f}→{t.get('exit',0):.2f}  "
                f"P&L: {sign}${t.get('pnl',0):,.2f}"
            )

    pos = state.get("position", {})
    if pos and pos.get("size", 0) != 0:
        lines += [
            "\n--- OPEN POSITION ---",
            f"  {pos.get('direction','?')} {pos.get('size',0)} contracts @ {pos.get('avg_entry',0):.2f}",
            f"  Unrealized P&L: ${pos.get('unrealized_pnl', 0):+,.2f}",
        ]

    lines.append("\n===========================================")
    return "\n".join(lines)


async def chat_with_deepseek(
    history: list[ChatMessage],
    app_state: dict,
    api_key: str,
    search_fn: Callable[[str], str] | None = None,
    on_tool_call: Callable[[str], None] | None = None,
) -> str:
    """
    Send a conversation to DeepSeek with full app context prepended.
    Supports up to 5 rounds of function-calling (web_search).
    Returns the final assistant text response.
    """
    if not api_key:
        return (
            "No DeepSeek API key configured. "
            "Set DEEPSEEK_API_KEY environment variable or add it to "
            "~/.config/backtest_tui/config.toml under [ai] deepseek_api_key."
        )

    context_block = build_context_block(app_state)
    system_msg = {
        "role": "system",
        "content": (
            "You are an expert futures trading analyst AI embedded in a professional "
            "backtesting terminal (Futures Backtest TUI). "
            "You have access to live backtest data, analytics, and prop firm status "
            "shown in the context block below. Use the web_search tool when the user "
            "asks for current news, company information, or anything not in the context.\n"
            "Be concise, precise, and reference specific numbers from the context.\n\n"
            + context_block
        ),
    }

    api_messages = [system_msg]
    for msg in history:
        m: dict = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            m["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            m["tool_call_id"] = msg.tool_call_id
        if msg.name:
            m["name"] = msg.name
        api_messages.append(m)

    tools = [SEARCH_TOOL_DEF] if search_fn else None

    async with httpx.AsyncClient(timeout=60.0) as client:
        for _ in range(5):
            payload: dict = {
                "model": DEEPSEEK_MODEL,
                "messages": api_messages,
                "temperature": 0.1,
                "max_tokens": 2048,
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            try:
                resp = await client.post(
                    DEEPSEEK_API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                return f"API error {exc.response.status_code}: {exc.response.text[:200]}"
            except Exception as exc:
                return f"Network error: {exc}"

            data = resp.json()
            choice = data["choices"][0]
            msg_data = choice["message"]
            finish_reason = choice.get("finish_reason", "stop")

            if finish_reason == "tool_calls" and msg_data.get("tool_calls"):
                api_messages.append(msg_data)
                for tc in msg_data["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"])
                    if fn_name == "web_search" and search_fn:
                        query = fn_args.get("query", "")
                        if on_tool_call:
                            on_tool_call(f"Searching: {query}")
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, search_fn, query
                        )
                        api_messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result or "No results found.",
                        })
                continue

            return msg_data.get("content", "")

    return "Error: max tool-call rounds reached."
