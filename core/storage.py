"""Постоянное хранение данных.

На Streamlit Community Cloud файл SQLite живёт только до перезапуска приложения (оно «засыпает»
без посетителей и при пробуждении стартует с чистого диска). Поэтому после каждого сохранения
снимок базы (JSON) записывается:
  1) локально — data/snapshot.json;
  2) в GitHub (если в secrets заданы GITHUB_TOKEN и GITHUB_REPO) — файл data/snapshot.json
     в отдельной ветке (по умолчанию «ecosvet-data», чтобы не перезапускать приложение).
При запуске с пустой базой снимок автоматически восстанавливается.
"""
from __future__ import annotations

import base64
import json
import os
import time

from . import db

SNAP_PATH = "data/snapshot.json"
STATUS = {"last_ok": None, "last_error": None, "target": "local", "block_push": False, "restored_from": None}


def _cfg(secrets: dict) -> dict | None:
    get = lambda k, d=None: secrets.get(k) or os.environ.get(k) or d  # noqa: E731
    token, repo = get("GITHUB_TOKEN"), get("GITHUB_REPO")
    if not token or not repo:
        return None
    return {"token": token, "repo": repo, "branch": get("GITHUB_BRANCH", "ecosvet-data"),
            "path": get("GITHUB_PATH", SNAP_PATH)}


def _gh(cfg, method, url, **kw):
    import requests
    return requests.request(method, f"https://api.github.com/repos/{cfg['repo']}{url}", timeout=20,
                            headers={"Authorization": f"Bearer {cfg['token']}",
                                     "Accept": "application/vnd.github+json"}, **kw)


def _ensure_branch(cfg) -> None:
    if _gh(cfg, "GET", f"/git/ref/heads/{cfg['branch']}").status_code == 200:
        return
    default = _gh(cfg, "GET", "").json()["default_branch"]
    sha = _gh(cfg, "GET", f"/git/ref/heads/{default}").json()["object"]["sha"]
    r = _gh(cfg, "POST", "/git/refs", json={"ref": f"refs/heads/{cfg['branch']}", "sha": sha})
    if r.status_code not in (200, 201, 422):
        r.raise_for_status()


def mode(secrets: dict) -> str:
    return "github" if _cfg(secrets) else "local"


def persist(secrets: dict, force: bool = False) -> tuple[bool, str]:
    """Сохраняет снимок базы. Возвращает (успех, сообщение)."""
    text = db.export_json()
    local = db.ROOT / SNAP_PATH
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, encoding="utf-8")
    db.DIRTY["flag"] = False
    cfg = _cfg(secrets)
    STATUS["target"] = "github" if cfg else "local"
    if not cfg:
        STATUS["last_ok"] = time.strftime("%H:%M:%S")
        return True, "Сохранено в базу (локально)."
    if STATUS["block_push"] and not force:
        return False, ("В базу сохранено. В GitHub не отправлено: при запуске не удалось загрузить данные оттуда "
                       "(защита от перезаписи). Перезапустите приложение или сохраните принудительно в «Администрирование».")
    try:
        _ensure_branch(cfg)
        cur = _gh(cfg, "GET", f"/contents/{cfg['path']}", params={"ref": cfg["branch"]})
        body = {"message": f"ЭкоСвет: сохранение данных {db.now()}", "branch": cfg["branch"],
                "content": base64.b64encode(text.encode("utf-8")).decode()}
        if cur.status_code == 200:
            body["sha"] = cur.json()["sha"]
        r = _gh(cfg, "PUT", f"/contents/{cfg['path']}", json=body)
        r.raise_for_status()
        STATUS["last_ok"], STATUS["last_error"], STATUS["block_push"] = time.strftime("%H:%M:%S"), None, False
        return True, f"Сохранено в базу и в GitHub ({cfg['repo']}, ветка {cfg['branch']})."
    except Exception as e:  # сеть, токен, права
        db.DIRTY["flag"] = True          # попробуем ещё раз при следующем действии
        STATUS["last_error"] = f"{type(e).__name__}: {e}"[:200]
        return False, f"В базу сохранено, но в GitHub — нет ({type(e).__name__}). Повторю при следующем сохранении."


def flush_if_dirty(secrets: dict) -> None:
    if db.DIRTY["flag"]:
        persist(secrets)


def restore(secrets: dict) -> str | None:
    """Восстанавливает данные из снимка (GitHub → локальный файл). Возвращает источник или None."""
    cfg = _cfg(secrets)
    if cfg:
        try:
            r = _gh(cfg, "GET", f"/contents/{cfg['path']}", params={"ref": cfg["branch"]})
            if r.status_code == 200:
                data = r.json()
                if data.get("content"):
                    text = base64.b64decode(data["content"]).decode("utf-8")
                else:  # файл > 1 МБ — берём через download_url
                    import requests
                    text = requests.get(data["download_url"], timeout=20,
                                        headers={"Authorization": f"Bearer {cfg['token']}"}).text
                db.import_json(text)
                db.DIRTY["flag"] = False
                STATUS["restored_from"] = "GitHub"
                return "GitHub"
            if r.status_code != 404:          # 404 — снимка ещё нет, это нормально
                STATUS["block_push"] = True
                STATUS["last_error"] = f"restore: HTTP {r.status_code}"
        except Exception as e:
            STATUS["block_push"] = True
            STATUS["last_error"] = f"restore: {type(e).__name__}: {e}"[:200]
    local = db.ROOT / SNAP_PATH
    if local.exists():
        try:
            json.loads(local.read_text(encoding="utf-8"))
            db.import_json(local.read_text(encoding="utf-8"))
            db.DIRTY["flag"] = False
            STATUS["restored_from"] = "локальный снимок"
            return "локальный снимок"
        except ValueError:
            return None
    return None
