"""Cypher statement modules.

One module per domain (accounts, people, ...), each exposing its statements as
module-level string constants. This package holds no logic -- only the
queries -- so the injection-safety and correctness of every statement can be
verified by reading this tree, without also reading every service that uses it.
"""

from __future__ import annotations
