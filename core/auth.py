"""Пользователи и роли: admin — редактирование, viewer — только просмотр и отзывы."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets

from . import db

ITER = 200_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITER).hex()
    return h, salt


def verify(password: str, pw_hash: str, salt: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[0], pw_hash)


def get_user(username: str) -> dict | None:
    return db.q1("SELECT * FROM users WHERE lower(username)=lower(?)", (username.strip(),))


def create_user(username: str, password: str, full_name: str = "", role: str = "viewer") -> tuple[bool, str]:
    username = username.strip()
    if not USERNAME_RE.match(username):
        return False, "Логин: 3–32 символа, латиница, цифры, _ . -"
    if len(password) < 6:
        return False, "Пароль должен быть не короче 6 символов"
    if get_user(username):
        return False, "Такой логин уже занят"
    h, s = hash_password(password)
    db.ex("INSERT INTO users(username, full_name, pw_hash, salt, role, created_at) VALUES (?,?,?,?,?,?)",
          (username, full_name.strip(), h, s, role, db.now()))
    return True, "Аккаунт создан"


def login(username: str, password: str) -> dict | None:
    u = get_user(username)
    if u and verify(password, u["pw_hash"], u["salt"]):
        return {k: u[k] for k in ("id", "username", "full_name", "role")}
    return None


def set_password(user_id: int, password: str) -> None:
    h, s = hash_password(password)
    db.ex("UPDATE users SET pw_hash=?, salt=? WHERE id=?", (h, s, user_id))


def set_role(user_id: int, role: str) -> None:
    db.ex("UPDATE users SET role=? WHERE id=?", (role, user_id))


def delete_user(user_id: int) -> None:
    db.ex("DELETE FROM users WHERE id=?", (user_id,))


def users() -> list[dict]:
    return db.q("SELECT id, username, full_name, role, created_at FROM users ORDER BY id")


def ensure_admin(secrets_dict: dict | None = None) -> bool:
    """Создаёт первого администратора. Возвращает True, если использован пароль по умолчанию."""
    if db.q1("SELECT id FROM users WHERE role='admin'"):
        return False
    secrets_dict = secrets_dict or {}
    user = secrets_dict.get("ADMIN_USERNAME") or os.environ.get("ADMIN_USERNAME") or "admin"
    pwd = secrets_dict.get("ADMIN_PASSWORD") or os.environ.get("ADMIN_PASSWORD")
    default = not pwd
    pwd = pwd or "admin123"
    existing = get_user(user)
    if existing:
        set_role(existing["id"], "admin")
        set_password(existing["id"], pwd)
    else:
        h, s = hash_password(pwd)
        db.ex("INSERT INTO users(username, full_name, pw_hash, salt, role, created_at) VALUES (?,?,?,?,?,?)",
              (user, "Администратор", h, s, "admin", db.now()))
    return default
