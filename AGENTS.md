# Repository Guidelines

## Project Structure & Module Organization

- `G903控制面板.pyw` is the user-facing Windows GUI launcher; `g903_battery.py`
  is the command-line battery reader.
- `g903_app/` contains the GUI, HID++ control logic, shared theme, and wave bar.
- `tools/probe_features.py` is a read-only HID++ feature probe. Keep diagnostics
  separate from settings writes.
- `tests/` contains lightweight checks. Runtime history is in `data/`.

## Build, Test, and Development Commands

Use Python directly; there is no build system or package manifest.

```powershell
pip install hid
python -m py_compile g903_battery.py g903_app\g903_control.py g903_app\g903_control_gui.py g903_app\g903_battery_wave.py g903_app\theme.py
python g903_battery.py
python -m tools.probe_features
python -m tests.test_control
python -m tests.test_gui
```

The compile command catches syntax errors without accessing hardware.
`tools.probe_features` and the battery reader access the connected G903. The
GUI test needs a working local Tk installation but does not intentionally
access hardware or append history.

## Development Process

For multi-step work, split it into independent subtasks (one per module or
concern) and dispatch them to parallel subagents to finish the pass in one
round. Run read-only exploration concurrently rather than sequentially, and
reuse later findings instead of re-reading files.

## Coding Style & Naming Conventions

Use Python with four-space indentation, `snake_case` for functions and
variables, `UPPER_CASE` for HID++ constants, and focused module-level helpers.
Keep HID++ packet construction and response parsing explicit; validate response
lengths before indexing. Prefer standard library modules and existing helpers
over new dependencies or framework layers. Preserve Chinese user-facing text
and save text files as UTF-8.

## Testing Guidelines

Add small, dependency-free assertions for parsing, status decoding, or packet
formatting changes. Name new checks `test_*.py` and keep hardware writes out of
tests. Manually verify DPI/report-rate writes only with the device connected;
read back the value after a write when changing that path.

## Commit & Pull Request Guidelines

The history contains only initial commits, so no established commit convention
exists. Use concise imperative subjects, for example `Fix report-rate error
frame matching`. Keep commits scoped to one behavior. PRs should state the
affected launcher/module, commands run, hardware used (if any), and include a
screenshot for visible Tkinter changes. Do not commit `.env`, `__pycache__`, or
personal HID history data.
