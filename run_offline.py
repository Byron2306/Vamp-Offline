
import sys
import os

# ✅ Add root directory to sys.path
sys.path.insert(0, os.path.abspath("."))

# ✅ Run the offline app GUI
from frontend.offline_app import offline_app_gui_llm_csv
