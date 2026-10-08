"""A helper the Pydantic AI examples share; not an example itself.

It runs an agent and prints what it does as it happens: its thinking, each tool call, the answer.
"""

import sys

from pydantic_ai import Agent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

# Thinking is printed dim, to tell it from the answer, when the output is a terminal.
DIM, RESET = ("\x1b[2m", "\x1b[0m") if sys.stdout.isatty() else ("", "")


async def run_and_print(agent: Agent, question: str) -> None:
    """Run `agent` on `question`, printing its thinking, tool calls and answer as they happen.

    Args:
        agent: The agent to run.
        question: The user's message.
    """
    async with agent.run_stream_events(question) as events:
        async for event in events:
            if isinstance(event, FunctionToolCallEvent):
                print(f"\n→ {event.part.tool_name} {event.part.args_as_json_str()}", flush=True)
            elif isinstance(event, FunctionToolResultEvent):
                failed = isinstance(event.part, RetryPromptPart)
                print(f"  {'✗ refused' if failed else '✓ done'}", flush=True)
            elif isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                print(f"\n{DIM}{event.part.content}", end="", flush=True)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
                print(event.delta.content_delta or "", end="", flush=True)
            elif isinstance(event, PartEndEvent) and isinstance(event.part, ThinkingPart):
                print(RESET, flush=True)
            elif isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                print(event.part.content, end="", flush=True)
            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                print(event.delta.content_delta, end="", flush=True)
    print()
