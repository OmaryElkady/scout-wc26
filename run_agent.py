"""Entry point for the Scout AI agent interactive CLI.

Run from the project root:

    python run_agent.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows consoles default to CP1252; reconfigure to UTF-8 so accented
# player names (e.g. Ján Greguš, Antonio Rüdiger) print correctly.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.agent.scout_agent import run_query  # noqa: E402

import logging  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

print("Scout AI Agent — type 'quit' or 'exit' to stop\n")

while True:
    try:
        question = input("Scout> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        sys.exit(0)

    if question.lower() in ("quit", "exit"):
        print("Goodbye.")
        sys.exit(0)

    if not question:
        continue

    print("\n" + run_query(question) + "\n")
