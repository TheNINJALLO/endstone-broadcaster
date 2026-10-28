"""Exercise the helper without loading Endstone's native server module."""

import sys
import types
from pathlib import Path

package = types.ModuleType("endstone_broadcaster")
package.__path__ = [
    str(Path(__file__).resolve().parents[1] / "src" / "endstone_broadcaster")
]
sys.modules["endstone_broadcaster"] = package
