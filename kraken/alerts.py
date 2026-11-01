"""Push alerts to ntfy.sh, Telegram and/or Discord. Standard library only; failures never break scans."""
from __future__ import annotations
import json, threading, time, urllib.parse, urllib.request


class Alerts:
    def __init__(self, settings):
        self.settings = settings
        self.sent: dict[str, float] = {}
        self.lock = threading.Lock()
        self.log: list[dict] = []

    def _post(self, url, data: bytes, headers: dict):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "kraken", **headers})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status

    def send(self, title: str, body: str, key: str | None = None, url: str | None = None, force=False) -> dict:
        a = self.settings.get("alerts")
        if not (a["enabled"] or force):
            return {}
        if key:
            with self.lock:
                if time.time() - self.sent.get(key, 0) < 6 * 3600:
                    return {}
                self.sent[key] = time.time()
        res = {}
        if a["ntfy_topic"]:
            try:
                h = {"Title": title.encode("ascii", "ignore").decode() or "kraken", "Tags": "octopus"}
                if url:
                    h["Click"] = url
                res["ntfy"] = self._post("https://ntfy.sh/" + urllib.parse.quote(a["ntfy_topic"]), body.encode(), h)
            except Exception as e:
                res["ntfy"] = str(e)[:120]
        if a["telegram_token"] and a["telegram_chat_id"]:
            try:
                q = json.dumps(dict(chat_id=a["telegram_chat_id"], text=f"🐙 {title}\n{body}" + (f"\n{url}" if url else ""),
                                    disable_web_page_preview=True)).encode()
                res["telegram"] = self._post(f"https://api.telegram.org/bot{a['telegram_token']}/sendMessage", q,
                                             {"Content-Type": "application/json"})
            except Exception as e:
                res["telegram"] = str(e)[:120]
        if a["discord_webhook"]:
            try:
                q = json.dumps(dict(username="kraken", content=f"**{title}**\n{body}" + (f"\n<{url}>" if url else ""))).encode()
                res["discord"] = self._post(a["discord_webhook"], q, {"Content-Type": "application/json"})
            except Exception as e:
                res["discord"] = str(e)[:120]
        self.log = ([dict(ts=time.time(), title=title, body=body, result=res)] + self.log)[:50]
        return res
