"""python -m kraken          start the dashboard (http://127.0.0.1:8420)
python -m kraken setup    connect your GMGN API key
python -m kraken doctor   check your install"""
from __future__ import annotations
import getpass, os, sys, webbrowser


def setup():
    """Terminal version of the setup page: same gmgn-cli config flow."""
    from . import setup_flow
    print("\n🐙 kraken setup\n")
    st = setup_flow.status()
    if not st["cli"]:
        print("gmgn-cli isn't installed. Install Node.js 18+, then run:  npm install -g gmgn-cli")
        return
    if st["api_key"] and input("A GMGN key is already connected. Replace it? [y/N] ").strip().lower() != "y":
        return
    link = setup_flow.start()["link"]
    print("1. Log in to GMGN in your browser.")
    print("2. Open this link (your public key is pre-filled), create the API key, and copy it:\n")
    print("   " + link + "\n")
    try:
        webbrowser.open(link)
    except Exception:
        pass
    key = getpass.getpass("3. Paste the API key here (input is hidden): ").strip()
    if not key:
        print("No key entered. Run  python -m kraken setup  again when you have it.")
        return
    r = setup_flow.apply(key)
    print({"ok": "\n✓ Connected. Start kraken and it will use live GMGN data.",
           "saved_unverified": "\nKey saved, but GMGN didn't answer the test call (often a network blip). Try starting kraken.",
           "auth_fail": "\n✗ GMGN rejected that key. Copy the whole key, and create it from the link above so it matches your key pair.",
           "no_keypair": "\n✗ Key pair missing. Run setup again."}.get(r["result"], "\n✗ " + r["message"]))


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
    print("gmgn-cli", "✓" if k["cli"] else "✗  npm install -g gmgn-cli")
    print("API key", "✓" if k["api_key"] else "✗  python -m kraken setup")
    ok &= k["cli"] and k["api_key"]
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
