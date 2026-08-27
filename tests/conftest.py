import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ / "src"))
# worker/ vive en la raiz del repo (no dentro de src/): es un consumidor de
# gemma_cum_loader, igual que ui_revision/ -- necesita la raiz en el path
# para que `tests/test_worker_*.py` pueda importarlo como paquete.
sys.path.insert(0, str(_RAIZ))
