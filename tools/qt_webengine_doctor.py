# -*- coding: utf-8 -*-
"""Run the same standard-mode Qt WebEngine diagnosis used by app startup."""

from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app_渠系计算前端.webengine_diagnostics import (  # noqa: E402
    format_probe_report,
    probe_result_json,
    probe_standard_webengine,
)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    result = probe_standard_webengine()
    print(format_probe_report(result))
    print("")
    print("JSON:")
    print(probe_result_json(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
