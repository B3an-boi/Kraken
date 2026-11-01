"""Run one of GMGN's vendored scripts with `gmgn-cli` resolved to its real path.

The scripts call subprocess.run(["gmgn-cli", ...]). On Windows gmgn-cli is a .cmd shim that
CreateProcess can't find by bare name, so every call is rewritten to the full path first.
Usage: python -m kraken.vendor.run <script.py> [args...]
"""
import os, runpy, shutil, subprocess, sys

_GMGN = shutil.which("gmgn-cli")


def _fix(args):
    if _GMGN and isinstance(args, (list, tuple)) and args and args[0] == "gmgn-cli":
        return [_GMGN, *args[1:]]
    return args


_run, _popen_init = subprocess.run, subprocess.Popen.__init__
subprocess.run = lambda args, *a, **k: _run(_fix(args), *a, **k)
subprocess.Popen.__init__ = lambda self, args, *a, **k: _popen_init(self, _fix(args), *a, **k)

if __name__ == "__main__":
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gmgn", os.path.basename(sys.argv[1]))
    sys.argv = [script, *sys.argv[2:]]
    runpy.run_path(script, run_name="__main__")
