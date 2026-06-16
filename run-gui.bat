@echo off
REM Launch the interactive LP -> ISK optimizer UI using the project venv.
REM pythonw.exe runs it without an extra console window.
"%~dp0.venv\Scripts\pythonw.exe" -m eve_lp.gui %*
