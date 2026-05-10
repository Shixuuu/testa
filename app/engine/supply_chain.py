"""AI-driven supply chain relationship graph and company report generation."""
from __future__ import annotations
import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Callable

import httpx
from rich.text import Text

from .ai_client import DEEPSEEK_API_URL, DEEPSEEK_MODEL, SEARCH_TOOL_DEF


@dataclass
class SupplyChainNode:
    ticker: str
    name: str
    relationship: str   # "supplier" | "customer" | "competitor" | "partner" | "subsidiary"
    depth: int = 0
    children: list["SupplyChainNode"] = field(default_factory=list)


@dataclass
class SupplyChainResult:
    root: SupplyChainNode
    degree_to_major: dict[str, int]
    summary: str        # plain-text description of connections


_REL_COLOR = {
    "supplier":   "#ff8c00",
    "customer":   "#00cc44",
    "competitor": "#ff3030",
    "partner":    "#00bfff",
    "subsidiary": "#cc88ff",
    "parent":     "#ffcc44",
    "root":       "#ffffff",
}
_REL_ICON = {
    "supplier":   "▲",
    "customer":   "▼",
    "competitor": "⚔",
    "partner":    "◈",
    "subsidiary": "⊂",
    "parent":     "⊃",
    "root":       "◆",
}


# ── DeepSeek helpers ───────────────────────────────────────────────────────────

async def _deepseek_call(
    messages: list[dict],
    api_key: str,
    search_fn: Callable[[str], str] | None,
    max_tokens: int = 3000,
) -> str:
    """Single-shot or tool-calling DeepSeek request; returns assistant text."""
    payload: dict = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }
    if search_fn:
        payload["tools"] = [SEARCH_TOOL_DEF]
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=90.0) as client:
        for _ in range(6):
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
            except Exception as exc:
                return f"API error: {exc}"

            data = resp.json()
            choice = data["choices"][0]
            msg = choice["message"]
            finish = choice.get("finish_reason", "stop")

            if finish == "tool_calls" and msg.get("tool_calls") and search_fn:
                payload["messages"] = list(payload["messages"]) + [msg]
                for tc in msg["tool_calls"]:
                    args = json.loads(tc["function"]["arguments"])
                    query = args.get("query", "")
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, search_fn, query
                    )
                    payload["messages"].append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result or "No results.",
                    })
                continue

            return msg.get("content", "")

    return "Error: max rounds reached."


# ── Supply chain fetch ─────────────────────────────────────────────────────────

async def fetch_supply_chain(
    ticker: str,
    company_name: str,
    api_key: str,
    search_fn: Callable[[str], str] | None = None,
) -> SupplyChainResult:
    if not api_key:
        root = SupplyChainNode(ticker=ticker, name=company_name, relationship="root")
        return SupplyChainResult(root=root, degree_to_major={}, summary="No API key.")

    prompt = f"""You are a supply chain and financial analyst. Research {company_name} (ticker: {ticker}).

Use web_search to find accurate supply chain information. Then return ONLY this exact JSON structure (no markdown fences, no explanation before or after):

{{"ticker":"{ticker}","name":"{company_name}","relationship":"root","children":[{{"ticker":"TSMC","name":"Taiwan Semiconductor","relationship":"supplier","children":[]}},{{"ticker":"EXAMPLE","name":"Example Corp","relationship":"customer","children":[]}}],"degrees":{{"AAPL":2,"NVDA":1,"MSFT":3}},"summary":"One sentence describing the most important supply chain fact."}}

Rules:
- Include 4-8 direct children with relationships: supplier, customer, competitor, partner, subsidiary, or parent
- Go 1-2 levels deep maximum
- degrees: how many hops this company is from each major company (AAPL, MSFT, NVDA, AMZN, GOOGL, TSLA, TSMC, INTC, AMD, QCOM)
- Only include major companies where connection exists within 4 hops
- summary: one concise sentence about the most notable supply chain relationship"""

    raw = await _deepseek_call(
        [{"role": "user", "content": prompt}],
        api_key,
        search_fn,
    )

    root, degrees, summary = _parse_response(raw, ticker, company_name)
    return SupplyChainResult(root=root, degree_to_major=degrees, summary=summary)


def _parse_response(
    text: str, ticker: str, company_name: str
) -> tuple[SupplyChainNode, dict[str, int], str]:
    # Strip markdown fences if present
    text = re.sub(r"```[a-z]*\n?", "", text).strip()

    # Find the outermost JSON object
    start = text.find("{")
    if start == -1:
        node = SupplyChainNode(ticker=ticker, name=company_name, relationship="root")
        return node, {}, "Could not parse supply chain data."

    # Use a simple brace-counting extractor to get the first complete JSON object
    depth = 0
    end = start
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    json_str = text[start:end]
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        node = SupplyChainNode(ticker=ticker, name=company_name, relationship="root")
        return node, {}, "JSON parse error."

    degrees: dict[str, int] = {}
    if "degrees" in data and isinstance(data["degrees"], dict):
        degrees = {k: int(v) for k, v in data["degrees"].items() if isinstance(v, (int, float))}

    summary = data.get("summary", "")
    root = _dict_to_node(data, depth=0)
    return root, degrees, summary


def _dict_to_node(d: dict, depth: int) -> SupplyChainNode:
    node = SupplyChainNode(
        ticker=str(d.get("ticker", "?")),
        name=str(d.get("name", d.get("ticker", "?"))),
        relationship=str(d.get("relationship", "unknown")),
        depth=depth,
    )
    for child in d.get("children", []):
        if isinstance(child, dict):
            node.children.append(_dict_to_node(child, depth + 1))
    return node


# ── ASCII graph render ─────────────────────────────────────────────────────────

def render_supply_chain(root: SupplyChainNode) -> Text:
    result = Text()
    result.append(" SUPPLY CHAIN ", style="bold black on #ff8c00")
    result.append(f"  {root.name}", style="bold #00bfff")
    result.append(f"  ({root.ticker})\n", style="dim #4a6b8a")
    result.append("\n")
    _render_node(result, root, prefix="", is_last=True, is_root=True)
    return result


def _render_node(
    result: Text,
    node: SupplyChainNode,
    prefix: str,
    is_last: bool,
    is_root: bool = False,
):
    if is_root:
        for i, child in enumerate(node.children):
            _render_node(result, child, "", i == len(node.children) - 1)
        return

    connector = "└─" if is_last else "├─"
    child_prefix = prefix + ("   " if is_last else "│  ")
    color = _REL_COLOR.get(node.relationship, "#6a8fb5")
    icon = _REL_ICON.get(node.relationship, "·")

    result.append(prefix, style="dim #2a4a6a")
    result.append(connector + " ", style="dim #4a6b8a")
    result.append(f"{icon} ", style=f"bold {color}")
    result.append(f"{node.ticker:<8}", style=f"bold {color}")
    result.append(f" {node.name}", style="#c8d8e8")
    result.append(f"  [{node.relationship}]", style=f"dim {color}")
    result.append("\n")

    for i, child in enumerate(node.children):
        _render_node(result, child, child_prefix, i == len(node.children) - 1)


def render_degree_panel(degrees: dict[str, int], summary: str) -> Text:
    result = Text()
    result.append(" NETWORK DISTANCE ", style="bold black on #1e3a5f")
    result.append("\n\n")
    if degrees:
        for company, hops in sorted(degrees.items(), key=lambda x: x[1]):
            bar = "●" * hops + "○" * max(0, 4 - hops)
            color = "#00cc44" if hops == 1 else "#ff8c00" if hops == 2 else "#6a8fb5"
            result.append(f"  {company:<8}", style=f"bold {color}")
            result.append(f" {bar} ", style="dim #4a6b8a")
            result.append(f"{hops} hop{'s' if hops != 1 else ''}\n", style=f"dim {color}")
    else:
        result.append("  No degree data yet.\n", style="dim #4a6b8a")

    if summary:
        result.append("\n")
        result.append(" KEY INSIGHT ", style="bold black on #1e3a5f")
        result.append("\n\n")
        result.append(f"  {summary}\n", style="italic #c8d8e8")

    return result


# ── Company report ─────────────────────────────────────────────────────────────

async def generate_company_report(
    ticker: str,
    company_name: str,
    sector: str,
    description: str,
    financials_summary: str,
    api_key: str,
    search_fn: Callable[[str], str] | None = None,
) -> str:
    if not api_key:
        return "No DeepSeek API key configured."

    prompt = f"""You are a professional equity research analyst. Write a comprehensive company report for:

Company: {company_name} (Ticker: {ticker})
Sector: {sector}

Business Description:
{description[:800]}

Key Financials:
{financials_summary}

Use web_search to find current news, recent earnings, and market position.

Structure your report with these exact sections:

## BUSINESS OVERVIEW
What the company does, its products/services, revenue model, key markets.

## COMPETITIVE POSITION
Market share, key competitors, competitive moats, positioning.

## FINANCIAL ANALYSIS
Revenue trends, margins, profitability, debt levels, cash generation.

## RECENT DEVELOPMENTS
Latest earnings, product launches, strategic moves, management changes.

## INVESTMENT CONSIDERATIONS
Bull case (3 points), Bear case (3 points), key catalysts to watch.

Be specific. Use numbers from the financials. Keep each section concise (3-5 sentences)."""

    try:
        return await _deepseek_call(
            [{"role": "user", "content": prompt}],
            api_key,
            search_fn,
            max_tokens=2500,
        )
    except Exception as exc:
        return f"Error generating report: {exc}"
