"""Print the plugin version declared in combat_text/__init__.py (PluginMeta)."""

from __future__ import annotations

import pathlib
import re
import sys

INIT = pathlib.Path(__file__).resolve().parent.parent / "combat_text" / "__init__.py"


def read_version() -> str:
    text = INIT.read_text(encoding="utf-8")
    m = re.search(r'version\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("could not find version=\"...\" in combat_text/__init__.py")
    return m.group(1)


if __name__ == "__main__":
    print(read_version())
