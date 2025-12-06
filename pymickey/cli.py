#!/usr/bin/env python3
"""
CLI-обёртка над runner.main, чтобы команда `pymickey` работала как консольный инструмент.
"""

from __future__ import annotations


def cli() -> int:
    """Entry-point для `pymickey` как консольной команды."""
    import sys

    from .runner import main as runner_main

    # main у тебя уже принимает argv: List[str]
    return runner_main(sys.argv)
