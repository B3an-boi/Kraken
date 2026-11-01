"""First-run GMGN connection, wrapping gmgn-cli's own `config` flow so kraken never handles key files:

  1. `gmgn-cli config`            creates (or reuses) an Ed25519 key pair in ~/.config/gmgn/keypair.pem
                                  and prints a gmgn.ai link with the public key pre-filled
  2. user creates the API key on that page and pastes it into kraken
  3. `gmgn-cli config --apply K`  writes API key + signing key to ~/.config/gmgn/.env and verifies
"""
from __future__ import annotations
import os, re, subprocess
from .gmgn import gmgn_bin, key_status

_LINK = re.compile(r"https://gmgn\.ai/ai/generateapi\?pbk=[^\s\"'<>]+")
_KEY_OK = re.compile(r"^[A-Za-z0-9_\-.:=+/]{8,512}$")


def _run(args: list[str], timeout=60) -> subprocess.CompletedProcess:
    exe = gmgn_bin()
    if not exe:
        raise RuntimeError("gmgn-cli isn't installed. Install Node.js, then run: npm install -g gmgn-cli")
    env = {**os.environ, "LANG": "en_US.UTF-8"}
    if "--use-system-ca" not in env.get("NODE_OPTIONS", ""):
        env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --use-system-ca").strip()
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, env=env,
                          encoding="utf-8", errors="replace")


def status() -> dict:
    k = key_status()
    return dict(**k, ready=k["cli"] and k["api_key"], can_trade=k["cli"] and k["api_key"] and k["private_key"])


def start() -> dict:
    """Create/reuse the key pair and return GMGN's pre-filled 'create API key' link."""
    out = _run(["config"])
    m = _LINK.search((out.stdout or "") + (out.stderr or ""))
    if not m:
        msg = (out.stderr or out.stdout or "").strip()[:300]
        raise RuntimeError(f"gmgn-cli didn't return a setup link. {msg}".strip())
    return dict(link=m.group(0))


def apply(api_key: str) -> dict:
    key = (api_key or "").strip()
    if not _KEY_OK.match(key):
        raise ValueError("That doesn't look like a GMGN API key. Copy the whole key from the GMGN page and paste it again.")
    out = _run(["config", "--apply", key], timeout=90)
    text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
    if out.returncode == 0 and "verified successfully" in text.lower():
        result = "ok"
    elif out.returncode == 0:
        result = "saved_unverified"          # written, but the check call failed (often a network blip)
    elif "keypair.pem not found" in text:
        result = "no_keypair"
    elif "does not match" in text.lower() or "verification failed" in text.lower():
        result = "auth_fail"
    else:
        result = "error"
    return dict(result=result, message=text[:600], **status())
