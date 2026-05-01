# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/config.py — хранилище всех настроек приложения.

Содержит:
  - PulsarConfig    — главный конфиг UI (тема, фон, позиция окна, вайтлист).
                      Файл: assets/pulsar_config.json
  - WhitelistState  — тонкая обёртка над PulsarConfig для данных белого списка.
                      Умеет мигрировать старый whitelist_state.json.
  - AppSettings     — настройки VPN-сессии (URL подписки, вайтлист приложений).
                      Файл: assets/settings.json
  - AppsRegistry    — реестр известных приложений (.exe).
                      Файл: assets/apps.json

Этот модуль не импортирует ничего из PyQt6 — только stdlib (json, os).
Все остальные модули ui/* могут свободно импортировать отсюда.
"""

import json
import os
import sys as _sys

# Базовая директория для ЧТЕНИЯ ресурсов (assets/)
_UI_DIR      = os.path.dirname(os.path.abspath(__file__))

def _get_assets_dir():
    if getattr(_sys, 'frozen', False):
        # PyInstaller 6+ кладёт datas в _internal/ рядом с exe
        exe_dir = os.path.dirname(_sys.executable)
        internal = os.path.join(exe_dir, '_internal')
        base = internal if os.path.isdir(internal) else exe_dir
        return os.path.join(base, 'assets')
    return os.path.join(os.path.dirname(_UI_DIR), 'assets')

_ASSETS_DIR  = _get_assets_dir()

# Рабочая директория для ЗАПИСИ конфигов
def _get_appdata_dir():
    if getattr(_sys, 'frozen', False):
        # onedir EXE: пишем рядом с Pulsar.exe (не в _internal — там read-only)
        return os.path.join(os.path.dirname(_sys.executable), "userdata")
    return _ASSETS_DIR  # В режиме исходников храним в assets/

_APPDATA_DIR = _get_appdata_dir()


# ══════════════════════════════════════════════════════════
#  PULSAR CONFIG — главный конфиг приложения
# ══════════════════════════════════════════════════════════

class PulsarConfig:
    """
    Читает и пишет assets/pulsar_config.json.

    Хранит всё что связано с внешним видом и состоянием окна:
    акцентный цвет, фоновое изображение, геометрию окна,
    порядок и состояние белого списка приложений.

    Структура JSON-файла::

        {
            "theme_color": "#2d9cdb",
            "custom_color": "#2d9cdb",
            "background_path": "",
            "bg_enabled": true,
            "window_x": -1,
            "window_y": -1,
            "window_w": 950,
            "window_h": 630,
            "whitelist_order": [],
            "whitelist_toggled": []
        }
    """

    _PATH = os.path.join(_APPDATA_DIR, "pulsar_config.json")

    _DEFAULT: dict = {
        "theme_color": "#2d9cdb",
        "custom_color": "#2d9cdb",
        "background_path": "",
        "bg_enabled": True,
        "window_x": -1,
        "window_y": -1,
        "window_w": 950,
        "window_h": 630,
        "whitelist_order": [],
        "whitelist_toggled": [],
    }

    # ── Чтение / запись ───────────────────────────────────

    @classmethod
    def load(cls) -> dict:
        """
        Загружает конфиг с диска.
        При любой ошибке (файл не найден, битый JSON) возвращает дефолт.
        Также дополняет файл недостающими ключами — для совместимости
        со старыми версиями конфига.
        """
        try:
            with open(cls._PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default_val in cls._DEFAULT.items():
                data.setdefault(key, default_val)
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            return dict(cls._DEFAULT)

    @classmethod
    def save(cls, data: dict) -> None:
        """Сохраняет словарь конфига на диск."""
        os.makedirs(os.path.dirname(cls._PATH), exist_ok=True)
        try:
            with open(cls._PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[PulsarConfig] Ошибка записи: {e}")

    # ── Удобные точечные геттер/сеттеры ──────────────────

    @classmethod
    def get(cls, key: str):
        """Возвращает значение одного ключа. При отсутствии — дефолт."""
        return cls.load().get(key, cls._DEFAULT.get(key))

    @classmethod
    def set(cls, key: str, value) -> None:
        """Обновляет один ключ и сохраняет файл."""
        data = cls.load()
        data[key] = value
        cls.save(data)

    @classmethod
    def set_many(cls, **kwargs) -> None:
        """Обновляет несколько ключей за одну запись на диск."""
        data = cls.load()
        data.update(kwargs)
        cls.save(data)


# ══════════════════════════════════════════════════════════
#  WHITELIST STATE — обёртка для данных белого списка
# ══════════════════════════════════════════════════════════

class WhitelistState:
    """
    Тонкая обёртка над PulsarConfig для работы с белым списком.

    Данные хранятся в pulsar_config.json под ключами
    'whitelist_order' и 'whitelist_toggled' — отдельного файла нет.

    При первом запуске автоматически мигрирует старый whitelist_state.json,
    если он существует рядом с исполняемым файлом.
    """

    # Путь к устаревшему файлу (лежит в корне проекта, рядом с main.py)
    _LEGACY_PATH = os.path.join(
        os.path.dirname(_ASSETS_DIR), "whitelist_state.json"
    )

    @classmethod
    def _migrate_legacy(cls) -> None:
        """
        Однократно переносит данные из whitelist_state.json в PulsarConfig.
        После успешной миграции переименовывает старый файл в .json.bak.
        """
        if not os.path.isfile(cls._LEGACY_PATH):
            return
        try:
            with open(cls._LEGACY_PATH, "r", encoding="utf-8") as f:
                old = json.load(f)
            cfg = PulsarConfig.load()
            # Переносим только если в новом конфиге ещё нет данных
            if not cfg.get("whitelist_order"):
                cfg["whitelist_order"] = old.get("added_order", [])
            if not cfg.get("whitelist_toggled"):
                cfg["whitelist_toggled"] = old.get("enabled", [])
            PulsarConfig.save(cfg)
            os.rename(cls._LEGACY_PATH, cls._LEGACY_PATH.replace(".json", ".json.bak"))
            print("[WhitelistState] Данные перенесены в pulsar_config.json")
        except (OSError, json.JSONDecodeError, ValueError) as e:
            print(f"[WhitelistState] Ошибка миграции: {e}")

    @classmethod
    def get_added_order(cls) -> list[str]:
        """Возвращает список имён приложений в порядке добавления."""
        cls._migrate_legacy()
        return list(PulsarConfig.load().get("whitelist_order", []))

    @classmethod
    def get_enabled(cls) -> list[str]:
        """Возвращает список имён приложений с включённым тогглом."""
        cls._migrate_legacy()
        return list(PulsarConfig.load().get("whitelist_toggled", []))

    @classmethod
    def set_state(cls, added_order: list[str], enabled: list[str]) -> None:
        """Сохраняет актуальное состояние белого списка в конфиг."""
        PulsarConfig.set_many(
            whitelist_order=added_order,
            whitelist_toggled=enabled,
        )


# ══════════════════════════════════════════════════════════
#  APP SETTINGS — настройки VPN-сессии
# ══════════════════════════════════════════════════════════

class AppSettings:
    """
    Читает и пишет assets/settings.json.

    Хранит параметры, которые влияют непосредственно на VPN-сессию:
    URL подписки, режим белого списка и список активных приложений.

    Структура JSON-файла::

        {
            "whitelist_enabled": false,
            "apps": [],
            "subscription_url": ""
        }
    """

    _PATH = os.path.join(_APPDATA_DIR, "settings.json")

    _DEFAULT: dict = {
        "whitelist_enabled": False,
        "apps": [],
        "subscription_url": "",
    }

    # ── Чтение / запись ───────────────────────────────────

    @classmethod
    def load(cls) -> dict:
        """Загружает настройки; при ошибке возвращает дефолт."""
        try:
            with open(cls._PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, default_val in cls._DEFAULT.items():
                data.setdefault(key, default_val)
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            return dict(cls._DEFAULT)

    @classmethod
    def save(cls, data: dict) -> None:
        """Сохраняет словарь настроек на диск."""
        try:
            with open(cls._PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            print(f"[AppSettings] Ошибка записи: {e}")

    # ── Удобные точечные геттер/сеттеры ──────────────────

    @classmethod
    def get_whitelist_enabled(cls) -> bool:
        """Возвращает True если режим белого списка включён."""
        return bool(cls.load().get("whitelist_enabled", False))

    @classmethod
    def set_whitelist_enabled(cls, enabled: bool) -> None:
        """Включает или выключает режим белого списка."""
        data = cls.load()
        data["whitelist_enabled"] = enabled
        cls.save(data)

    @classmethod
    def get_apps(cls) -> list[str]:
        """Возвращает список exe-имён приложений из белого списка."""
        return list(cls.load().get("apps", []))

    @classmethod
    def set_apps(cls, apps: list[str]) -> None:
        """Сохраняет список exe-имён приложений белого списка."""
        data = cls.load()
        data["apps"] = apps
        cls.save(data)


# ══════════════════════════════════════════════════════════
#  APPS REGISTRY — реестр известных приложений
# ══════════════════════════════════════════════════════════

_APPS_JSON_PATH = os.path.join(_APPDATA_DIR, "apps.json")

_APPS_JSON_DEFAULT: list[dict] = [
    {"name": "Telegram", "exe": "Telegram.exe"},
    {"name": "Discord", "exe": "Discord.exe"},
    {"name": "Spotify", "exe": "Spotify.exe"},
    {"name": "Minecraft", "exe": "javaw.exe"},
    {"name": "Yandex", "exe": "browser.exe"},
]

# Глобальный кеш: name -> exe. Обновляется через reload_app_exe_map().
APP_EXE_MAP: dict[str, str] = {}


def load_apps_json() -> list[dict]:
    """
    Загружает список приложений из userdata/apps.json (EXE) или assets/apps.json (dev).
    При первом запуске EXE копирует шаблон из _internal/assets/apps.json.
    """
    # В frozen-режиме: если в userdata ещё нет apps.json,
    # копируем шаблон из _internal/assets/ (read-only источник)
    if getattr(_sys, 'frozen', False) and not os.path.isfile(_APPS_JSON_PATH):
        _template = os.path.join(_ASSETS_DIR, 'apps.json')
        if os.path.isfile(_template):
            import shutil
            os.makedirs(os.path.dirname(_APPS_JSON_PATH), exist_ok=True)
            try:
                shutil.copy2(_template, _APPS_JSON_PATH)
            except OSError:
                pass

    if not os.path.isfile(_APPS_JSON_PATH):
        save_apps_json(_APPS_JSON_DEFAULT)
        return list(_APPS_JSON_DEFAULT)
    try:
        with open(_APPS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("apps", [])
    except (OSError, json.JSONDecodeError, ValueError):
        return list(_APPS_JSON_DEFAULT)


def save_apps_json(apps: list[dict]) -> None:
    """Сохраняет список приложений в assets/apps.json."""
    try:
        os.makedirs(os.path.dirname(_APPS_JSON_PATH), exist_ok=True)
        with open(_APPS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump({"apps": apps}, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[AppsRegistry] Ошибка записи: {e}")


def reload_app_exe_map() -> None:
    """Перечитывает apps.json и обновляет глобальный кеш APP_EXE_MAP."""
    global APP_EXE_MAP
    APP_EXE_MAP = {a["name"]: a["exe"] for a in load_apps_json()}


def add_app(name: str, exe: str) -> bool:
    """
    Добавляет приложение в apps.json и обновляет кеш APP_EXE_MAP.

    Возвращает True при успехе, False если приложение с таким именем
    или exe уже существует в реестре (проверка без учёта регистра).
    """
    apps = load_apps_json()
    for existing in apps:
        if (existing["name"].lower() == name.lower()
                or existing["exe"].lower() == exe.lower()):
            return False
    apps.append({"name": name, "exe": exe})
    save_apps_json(apps)
    reload_app_exe_map()
    return True


# Инициализируем кеш при загрузке модуля
reload_app_exe_map()