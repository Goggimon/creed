import subprocess
import sys
import os

# Activate venv python
python_exe = sys.executable

# Start backend (new terminal window)
backend = subprocess.Popen(
    [python_exe, "-m", "uvicorn", "api.server:app", "--reload"],
    creationflags=subprocess.CREATE_NEW_CONSOLE,
)

# Start GUI
gui = subprocess.Popen([python_exe, "gui/app.py"])

# Wait for GUI to close
gui.wait()

# Kill backend when GUI closes
backend.terminate()
