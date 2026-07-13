from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.vectorstore.index_manager import IndexManager  # noqa: E402

if __name__ == "__main__":
    manager = IndexManager()
    chunks = manager.rebuild()
    print({"chunk_count": len(chunks), **manager.last_summary})
