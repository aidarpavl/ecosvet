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


class GitHubError(Exception):
    """Понятное сообщение об ошибке GitHub."""


def normalize_repo(repo: str) -> str:
    """Принимает «owner/repo», «https://github.com/owner/repo», «...repo.git» и т. п."""
    r = str(repo).strip().strip('"').strip("'").strip()
    for pref in ("https://", "http://", "www.", "github.com/", "api.github.com/repos/"):
        if r.lower().startswith(pref):
            r = r[len(pref):]
    r = r.split("?")[0].split("#")[0].strip("/")
    if r.endswith(".git"):
        r = r[:-4]
    parts = [x for x in r.split("/") if x]
    return "/".join(parts[:2])


def _cfg(secrets: dict) -> dict | None:
    get = lambda k, d=None: secrets.get(k) or os.environ.get(k) or d  # noqa: E731
    token, repo = get("GITHUB_TOKEN"), get("GITHUB_REPO")
    if not token or not repo:
        return None
    return {"token": str(token).strip().strip('"').strip("'").strip(), "repo": normalize_repo(repo),
            "branch": str(get("GITHUB_BRANCH", "ecosvet-data")).strip() or "ecosvet-data",
            "path": str(get("GITHUB_PATH", SNAP_PATH)).strip().strip("/") or SNAP_PATH}


def _gh(cfg, method, url, **kw):
    import requests
    try:
        return requests.request(method, f"https://api.github.com/repos/{cfg['repo']}{url}", timeout=20,
                                headers={"Authorization": f"Bearer {cfg['token']}",
                                         "Accept": "application/vnd.github+json",
                                         "X-GitHub-Api-Version": "2022-11-28"}, **kw)
    except Exception as e:
        raise GitHubError(f"Нет связи с GitHub ({type(e).__name__}). Проверьте интернет и повторите.") from e


def _explain(r, what: str, cfg) -> str:
    try:
        gh_msg = (r.json() or {}).get("message", "")
    except ValueError:
        gh_msg = r.text[:120]
    code = r.status_code
    if code == 401:
        hint = "токен GITHUB_TOKEN неверный или истёк — создайте новый и вставьте в Secrets без пробелов и кавычек"
    elif code == 403 and "rate limit" in gh_msg.lower():
        hint = "превышен лимит запросов GitHub — повторите через несколько минут"
    elif code == 403:
        hint = ("у токена нет прав на запись. В настройках fine-grained токена: Repository permissions → "
                "Contents → Read and write")
    elif code == 404:
        hint = (f"репозиторий «{cfg['repo']}» не найден или токен не имеет к нему доступа. Проверьте GITHUB_REPO "
                "(формат: логин/репозиторий) и в настройках токена: Repository access → Only select repositories → "
                "выберите этот репозиторий")
    elif code == 409:
        hint = "репозиторий пустой — добавьте в него хотя бы один файл (например, README) и повторите"
    elif code == 422:
        hint = f"GitHub отклонил запрос: {gh_msg}"
    else:
        hint = f"ответ GitHub {code}: {gh_msg}"
    return f"{what}: {hint} (HTTP {code})."


def _ok(r, what: str, cfg, allow=(200, 201)):
    if r.status_code not in allow:
        raise GitHubError(_explain(r, what, cfg))
    return r


def _json(r, what: str, cfg) -> dict:
    try:
        d = r.json()
    except ValueError:
        raise GitHubError(f"{what}: GitHub вернул непонятный ответ.")
    if not isinstance(d, dict):
        raise GitHubError(f"{what}: неожиданный ответ GitHub (по пути GITHUB_PATH лежит папка, а не файл?).")
    return d


def _ensure_branch(cfg) -> None:
    r = _gh(cfg, "GET", f"/git/ref/heads/{cfg['branch']}")
    if r.status_code == 200:
        return
    if r.status_code != 404:
        _ok(r, "Проверка ветки для данных", cfg)
    repo = _json(_ok(_gh(cfg, "GET", ""), "Доступ к репозиторию", cfg), "Доступ к репозиторию", cfg)
    default = repo.get("default_branch") or "main"
    ref = _json(_ok(_gh(cfg, "GET", f"/git/ref/heads/{default}"), f"Основная ветка «{default}»", cfg),
                "Основная ветка", cfg)
    sha = (ref.get("object") or {}).get("sha")
    if not sha:
        raise GitHubError(f"Не удалось прочитать основную ветку «{default}».")
    r = _gh(cfg, "POST", "/git/refs", json={"ref": f"refs/heads/{cfg['branch']}", "sha": sha})
    _ok(r, f"Создание ветки «{cfg['branch']}» для данных", cfg, allow=(200, 201, 422))


def check_github(secrets: dict) -> list[tuple[bool, str]]:
    """Пошаговая проверка подключения — для кнопки в «Администрирование»."""
    cfg = _cfg(secrets)
    if not cfg:
        return [(False, "В Secrets нет GITHUB_TOKEN и/или GITHUB_REPO.")]
    steps = [(True, f"Репозиторий: {cfg['repo']} · ветка для данных: {cfg['branch']} · файл: {cfg['path']}")]
    if "/" not in cfg["repo"]:
        return steps + [(False, "GITHUB_REPO должен быть в формате «логин/репозиторий», например «school/ecosvet».")]
    try:
        repo = _json(_ok(_gh(cfg, "GET", ""), "Доступ к репозиторию", cfg), "Доступ к репозиторию", cfg)
        steps.append((True, f"Репозиторий найден ({'приватный' if repo.get('private') else 'публичный'})."))
        perms = repo.get("permissions") or {}
        if perms and not perms.get("push"):
            steps.append((False, "У токена нет права записи (Contents → Read and write)."))
            return steps
        _ensure_branch(cfg)
        steps.append((True, f"Ветка «{cfg['branch']}» готова."))
        ok, msg = persist(secrets, force=True)
        steps.append((ok, msg))
    except GitHubError as e:
        steps.append((False, str(e)))
    return steps


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
            sha = _json(cur, "Чтение сохранённого файла", cfg).get("sha")
            if sha:
                body["sha"] = sha
        elif cur.status_code != 404:
            _ok(cur, "Чтение сохранённого файла", cfg)
        _ok(_gh(cfg, "PUT", f"/contents/{cfg['path']}", json=body), "Запись файла с данными", cfg)
        STATUS["last_ok"], STATUS["last_error"], STATUS["block_push"] = time.strftime("%H:%M:%S"), None, False
        return True, f"Сохранено в базу и в GitHub ({cfg['repo']}, ветка {cfg['branch']})."
    except Exception as e:  # сеть, токен, права
        db.DIRTY["flag"] = True          # попробуем ещё раз при следующем сохранении
        why = str(e) if isinstance(e, GitHubError) else f"{type(e).__name__}: {e}"
        STATUS["last_error"] = why[:400]
        return False, f"В базу сохранено, но в GitHub — нет. {why}"


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
                data = _json(r, "Загрузка данных из GitHub", cfg)
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
            if r.status_code != 404:          # 404 — снимка (или ветки) ещё нет, это нормально
                STATUS["block_push"] = True
                STATUS["last_error"] = "Загрузка при запуске: " + _explain(r, "чтение данных", cfg)
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
