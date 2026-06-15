import json
import os
import bcrypt
from pathlib import Path

CONFIG_DIR = Path(__file__).parent / "data"
CONFIG_FILE = CONFIG_DIR / "config.json"
TOKENS_FILE = CONFIG_DIR / "tokens.json"
DB_FILE = CONFIG_DIR / "flowith.db"

CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "server_host": "0.0.0.0",
    "server_port": 8000,
    "admin_username": "admin",
    "admin_password_hash": bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode(),
    "api_key": "sk-flowith",
    "proxy_enabled": False,
    "proxy_url": "",
    "debug": False,
    "tokens": []
}


class Config:
    def __init__(self):
        self._data = self._load()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except:
                pass
        return dict(DEFAULT_CONFIG)

    def _save(self):
        CONFIG_FILE.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        return self._data.get(name)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._save()

    def update(self, d):
        self._data.update(d)
        self._save()

    @property
    def admin_password_hash(self):
        return self._data.get("admin_password_hash", "")

    @admin_password_hash.setter
    def admin_password_hash(self, value):
        self._data["admin_password_hash"] = value
        self._save()

    @property
    def api_key(self):
        return self._data.get("api_key", "sk-flowith")

    @api_key.setter
    def api_key(self, value):
        self._data["api_key"] = value
        self._save()

    @property
    def server_host(self):
        return self._data.get("server_host", "0.0.0.0")

    @property
    def server_port(self):
        return self._data.get("server_port", 8000)

    @property
    def admin_username(self):
        return self._data.get("admin_username", "admin")


config = Config()
