from pathlib import Path

# Base directory for the backend package
BASE_DIR = Path(__file__).resolve().parent

# Core data dirs
DATA_DIR = BASE_DIR / "data"
BRAIN_DATA_DIR = DATA_DIR / "nwu_brain"
STATE_DIR = DATA_DIR / "states"
STORE_DIR = DATA_DIR / "store"

__all__ = [
    "BASE_DIR",
    "DATA_DIR",
    "BRAIN_DATA_DIR",
    "STATE_DIR",
    "STORE_DIR",
]
