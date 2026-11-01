"""python -m kraken          start the dashboard (http://127.0.0.1:8420)
python -m kraken setup    connect your GMGN API key (optional — demo mode needs none)
python -m kraken doctor   check your install"""
from __future__ import annotations
import getpass, os, sys, webbrowser


def setup():
    from .gmgn import GMGN_ENV, gmgn_bin, key_status, write_env
    print("\n🐙 kraken setup\n")
    if not gmgn_bin():
        print("gmgn-cli isn't installed. Install Node.js 18+, then run:  npm install -g gmgn-cli")
        print("(You can skip this — kraken runs on demo data without it.)\n")
    print("Get an API key at https://gmgn.ai/ai (it's bound to your IP and your Ed25519 public key).")
    print(f"Keys are saved only on this computer, in {GMGN_ENV}\n")
    k = getpass.getpass("GMGN API key (Enter to skip): ").strip()
    if not k:
        print("Skipped. kraken will use demo data.")
        return
    print("\nThe private (signing) key is ONLY needed for LIVE trading. Leave it empty to stay paper-only.")
    pk = getpass.getpass("GMGN private key (Enter to skip): ").strip()
    write_env(k, pk)
    s = key_status()
    print(f"\nSaved. API key: {'✓' if s['api_key'] else '✗'} · private key: {'✓' if s['private_key'] else '— (paper only)'}")
    print("Restart kraken to switch to live data.")


def doctor():
    from .gmgn import key_status
    ok = True
    print(f"Python {sys.version.split()[0]}", "✓" if sys.version_info >= (3, 10) else "✗ need 3.10+")
    ok &= sys.version_info >= (3, 10)
    for mod in ("fastapi", "uvicorn"):
        try:
            __import__(mod); print(f"{mod} ✓")
        except ImportError:
            print(f"{mod} ✗  (pip install -r requirements.txt)"); ok = False
    k = key_status()
    print("gmgn-cli", "✓" if k["cli"] else "— not installed (demo data only)")
    print("API key", "✓" if k["api_key"] else "— not set (demo data only)")
    print("private key", "✓ (LIVE trading possible)" if k["private_key"] else "— not set (paper trading only)")
    print("\nAll good." if ok else "\nFix the ✗ items above.")


def serve():
    import uvicorn
    host = os.getenv("KRAKEN_HOST", "127.0.0.1")
    port = int(os.getenv("KRAKEN_PORT", "8420"))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    print(f"\n🐙 kraken → {url}   (Ctrl+C to stop)\n")
    if os.getenv("KRAKEN_NO_BROWSER", "") == "":
        try:
            webbrowser.open(url)
        except Exception:
            pass
    uvicorn.run("kraken.server:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    {"setup": setup, "doctor": doctor, "serve": serve}.get(cmd, lambda: print(__doc__))()
