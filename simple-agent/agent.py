"""A minimal command-line agent built on the Anthropic Messages API.

Run it with: python agent.py
Requires the ANTHROPIC_API_KEY environment variable to be set.
"""

import os
import sys

from anthropic import Anthropic

MODEL = "claude-sonnet-5"

TOOLS = [
    {
        "name": "get_time",
        "description": "Get the current date and time.",
        "input_schema": {"type": "object", "properties": {}},
    }
]


def get_time() -> str:
    from datetime import datetime

    return datetime.now().isoformat()


def run_tool(name: str, tool_input: dict) -> str:
    if name == "get_time":
        return get_time()
    return f"Unknown tool: {name}"


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    client = Anthropic(api_key=api_key)
    messages = []

    print("Simple agent ready. Type 'exit' to quit.")
    while True:
        user_input = input("\nyou> ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})

        while True:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=TOOLS,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                for block in response.content:
                    if block.type == "text":
                        print(f"\nagent> {block.text}")
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        }
                    )
            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
