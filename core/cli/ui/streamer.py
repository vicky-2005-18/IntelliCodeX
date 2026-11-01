"""
Flicker-Free Live Token Streaming Subsystem for IntelliCodeX CLI.

Streams LLM response tokens into an unformatted character buffer during real-time
generation to prevent partial-markdown rendering glitches (such as unclosed code fences
or asterisks). Upon generation completion, renders the accumulated text as a polished
Rich Markdown panel.
"""

from typing import Callable, Iterable, List, Optional
import sys
import time

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


def _suspend_active_spinners() -> None:
    """Safely stop any active mascot spinners to prevent visual corruption during streaming."""
    try:
        for mod_name in ("core.cli.ui.banner", "core.cli.terminal_safety", "cli"):
            if mod_name in sys.modules:
                mod = sys.modules[mod_name]
                if hasattr(mod, "MascotSpinner") and hasattr(mod.MascotSpinner, "stop_all"):
                    mod.MascotSpinner.stop_all()
    except Exception:
        pass


class TokenStreamer:
    """
    Renders live LLM token streams into the terminal without flicker.
    Accumulates tokens in an unformatted buffer during generation,
    then renders a polished Markdown panel upon completion.
    """

    def __init__(
        self,
        console: Optional[Console] = None,
        refresh_per_second: float = 15.0,
    ) -> None:
        self.console: Console = console if console is not None else Console()
        self.refresh_per_second: float = refresh_per_second
        self._cancelled: bool = False
        self._live: Optional[Live] = None

    def cancel(self) -> None:
        """Safely halts streaming and flushes partial output."""
        self._cancelled = True

    def render_markdown_panel(
        self,
        text: str,
        title: str = "Answer",
        border_style: str = "cyan",
    ) -> None:
        """Renders formatted Markdown panel inside the console."""
        try:
            md = Markdown(text)
            panel = Panel(
                md,
                title=f"[bold {border_style}]{title}[/bold {border_style}]",
                border_style=border_style,
                padding=(1, 2),
            )
            self.console.print(panel)
        except Exception:
            # Fallback to plain Text panel if Markdown parsing or rendering encounters an issue
            panel = Panel(
                Text(text),
                title=f"[bold {border_style}]{title}[/bold {border_style}]",
                border_style=border_style,
                padding=(1, 2),
            )
            self.console.print(panel)

    def stream(
        self,
        token_generator: Iterable[str],
        title: str = "Answer",
        on_token: Optional[Callable[[str], None]] = None,
        border_style: str = "cyan",
    ) -> str:
        """
        Streams tokens into a flicker-free Live buffer and finalizes with a Rich Markdown panel.
        Handles KeyboardInterrupt cleanly by returning accumulated text without traceback.
        """
        self._cancelled = False
        _suspend_active_spinners()

        accumulated: List[str] = []
        interval: float = 1.0 / self.refresh_per_second if self.refresh_per_second > 0 else 0.0
        last_refresh: float = 0.0

        try:
            with Live(
                console=self.console,
                refresh_per_second=self.refresh_per_second,
                auto_refresh=False,
                transient=True,
            ) as live:
                self._live = live
                for token in token_generator:
                    if self._cancelled:
                        break

                    accumulated.append(token)
                    if on_token is not None:
                        on_token(token)

                    now = time.monotonic()
                    if now - last_refresh >= interval:
                        current_text = "".join(accumulated)
                        live.update(
                            Panel(
                                Text(current_text),
                                title=f"[bold {border_style}]{title}[/bold {border_style}]",
                                border_style=border_style,
                                padding=(1, 2),
                            ),
                            refresh=True,
                        )
                        last_refresh = now
        except KeyboardInterrupt:
            self._cancelled = True
        finally:
            self._live = None

        full_text = "".join(accumulated)
        if full_text:
            self.render_markdown_panel(full_text, title=title, border_style=border_style)

        return full_text


def render_markdown_panel(
    md_text: str,
    title: str = "Answer",
    border_style: str = "cyan",
    console: Optional[Console] = None,
) -> None:
    """
    Renders Markdown text inside a styled terminal panel.
    Drop-in replacement for legacy cli.py render_markdown_panel.
    """
    streamer = TokenStreamer(console=console)
    streamer.render_markdown_panel(md_text, title=title, border_style=border_style)


__all__ = [
    "TokenStreamer",
    "render_markdown_panel",
]
