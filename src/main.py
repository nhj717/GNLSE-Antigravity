"""Desktop Application Bootstrap for GNLSE Simulator."""

import sys
from pathlib import Path

# Ensure repository root is in sys.path so running directly via `python src/main.py` works seamlessly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PyQt6.QtWidgets import QApplication
from src.gui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
