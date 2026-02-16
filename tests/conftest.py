import sys
from pathlib import Path

# Add repo root to sys.path so imports like `import services...` always work
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
