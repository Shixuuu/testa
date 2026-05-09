"""AI Chat Panel — DeepSeek-powered side panel with full app context injection."""
from __future__ import annotations
import asyncio
from typing import Callable, Optional

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.reactive import reactive
from rich.text import Text
from rich.rule import Rule

from ..engine.ai_client import ChatMessage, chat_with_deepseek, get_api_key
from ..engine.news_fetcher import web_search


_BB_ORANGE = "bold #ff8c00"
_BB_CYAN = "#00bfff"
_BB_DIM = "#4a6b8a"
_BB_USER = "#c8d8e8"
_BB_ASSISTANT = "#e8e8e8"
_BB_TOOL = "italic #88aacc"


class ChatBubble(Static):
    """A single message bubble in the chat history."""

    DEFAULT_CSS = """
    ChatBubble {
        padding: 0 1;
        margin-bottom: 1;
    }
    """


class AIChatPanel(Widget):
    """
    Bloomberg-style AI chat sidebar.
    Pulls the DeepSeek API key from env / config. Sends the full app state
    as system context with every request.
    """

    DEFAULT_CSS = """
    AIChatPanel {
        background: #070d18;
        border: solid #1e3a5f;
        width: 42;
        display: none;
        layout: vertical;
    }

    AIChatPanel.visible {
        display: block;
    }

    #chat_header {
        background: #0a1628;
        color: #ff8c00;
        text-style: bold;
        height: 3;
        padding: 1 2;
        border-bottom: solid #1e3a5f;
    }

    #chat_history {
        height: 1fr;
        overflow-y: auto;
        padding: 1 1;
    }

    #chat_status {
        height: 1;
        color: #4a6b8a;
        padding: 0 2;
        text-align: left;
    }

    #chat_input {
        height: 3;
        border: solid #1e3a5f;
        border-top: solid #ff8c00;
        background: #0d1520;
    }

    #chat_input > Input {
        background: #0d1520;
        color: #e8e8e8;
        border: none;
        padding: 0 1;
    }
    """

    is_open: reactive[bool] = reactive(False)

    def __init__(self, state_provider: Callable[[], dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._state_provider = state_provider or (lambda: {})
        self._history: list[ChatMessage] = []
        self._api_key: str = get_api_key()
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Static(
            "  DeepSeek AI Analyst  [\\ to close]",
            id="chat_header",
        )
        yield ScrollableContainer(id="chat_history")
        yield Static("Ready. Type a question and press Enter.", id="chat_status")
        with Vertical(id="chat_input"):
            yield Input(placeholder="Ask about your strategy, markets, news…", id="chat_box")

    def toggle(self):
        self.is_open = not self.is_open
        if self.is_open:
            self.add_class("visible")
            self.query_one("#chat_box", Input).focus()
        else:
            self.remove_class("visible")

    def set_api_key(self, key: str):
        self._api_key = key

    async def on_input_submitted(self, event: Input.Submitted):
        if self._busy:
            return
        user_text = event.value.strip()
        if not user_text:
            return
        event.input.value = ""
        await self._send(user_text)

    async def _send(self, user_text: str):
        self._busy = True
        status = self.query_one("#chat_status", Static)
        status.update("Thinking…")

        self._add_bubble("You", user_text, _BB_USER)
        self._history.append(ChatMessage(role="user", content=user_text))

        def on_tool_call(msg: str):
            self.call_from_thread(status.update, f"  {msg}")

        try:
            app_state = self._state_provider()
            response = await chat_with_deepseek(
                history=self._history,
                app_state=app_state,
                api_key=self._api_key,
                search_fn=web_search,
                on_tool_call=on_tool_call,
            )
        except Exception as exc:
            response = f"Error: {exc}"

        self._history.append(ChatMessage(role="assistant", content=response))
        self._add_bubble("DeepSeek", response, _BB_ASSISTANT)
        status.update(f"Ready  ({len(self._history)//2} exchanges)")
        self._busy = False

    def _add_bubble(self, role: str, content: str, style: str):
        history = self.query_one("#chat_history", ScrollableContainer)
        label_style = _BB_ORANGE if role == "DeepSeek" else _BB_CYAN
        text = Text()
        text.append(f" {role} ", style=label_style + " bold")
        text.append("\n")
        text.append(content, style=style)
        bubble = ChatBubble(text)
        history.mount(bubble)
        # Scroll to bottom
        history.scroll_end(animate=False)

    def inject_context_message(self, summary: str):
        """Pre-load a context summary (e.g. after backtest completes)."""
        self._add_bubble(
            "System",
            f"Backtest context updated:\n{summary}",
            _BB_TOOL,
        )
