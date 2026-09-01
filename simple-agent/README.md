# simple-agent

A minimal command-line agent built on the Anthropic Messages API. It runs a
chat loop and has one example tool (`get_time`) to demonstrate tool use.

## Setup

```
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key-here
```

## Run

```
python agent.py
```

Type a message and press enter. Type `exit` to quit.
