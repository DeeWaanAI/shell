"""Layer 6 — Shell / integration prototype (grows the frozen pre-flight).

Public surface is deliberately small; the modules wire the frozen contracts of
L1..L5 into one runtime kernel that owns ``ds:shell_audit`` and never assumes
authority below the display.

Interpreter pin: Python 3.12 (matches ``preflight/spine.py``). Importing this
package exits loudly on an older interpreter rather than producing a false
failure.
"""
from . import _bootstrap  # noqa: F401  (interpreter guard + sys.path wiring)

__all__ = ["_bootstrap"]
