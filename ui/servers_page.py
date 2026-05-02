# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/servers_page.py — страница серверов и управления VPN-подключением.

Содержит:
  - SubscriptionLoader      — QThread: загружает подписку, парсит серверы, меряет пинг.
  - VpnConnectWorker        — QThread: запускает/останавливает sing-box + системный прокси.
  - DeleteConfirmDialog     — оверлей подтверждения удаления подписки.
  - VpnWarnOverlay          — оверлей «VPN активен, действие невозможно».
  - AddSubscriptionDialog   — оверлей ввода URL подписки.
  - ServersPage             — главная страница: список подписок + кнопка питания + таймер.

Зависимости:
  ui.theme   — ThemeManager, функции стилей.
  ui.config  — AppSettings.
  ui.widgets — GlassCard, VpnSubscriptionCard, PowerButton, ToggleSwitch.
"""

import datetime
import re
import threading
import logging
logger = logging.getLogger(__name__)

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap, QIcon
from PyQt6.QtWidgets import (
    QGraphicsBlurEffect, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ui.theme import ThemeManager, scrollbar_ss, themed_btn_ss, themed_strong_btn_ss
from ui.config import AppSettings
from ui.widgets import (
    GlassCard, PowerButton, ToggleSwitch, VpnSubscriptionCard,
)

# Проверяем доступность модуля парсера
import sys as _sys
import os as _os
_PROJECT_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _PROJECT_DIR not in _sys.path:
    _sys.path.insert(0, _PROJECT_DIR)

try:
    from core.parser import fetch_subscription, parse_any_link, get_flag_emoji
    _PARSER_OK = True
except ImportError:
    try:
        from parser import fetch_subscription, parse_any_link, get_flag_emoji
        _PARSER_OK = True
    except ImportError:
        _PARSER_OK = False


# ══════════════════════════════════════════════════════════
#  ВОРКЕР — загрузка подписки + параллельный пинг
# ══════════════════════════════════════════════════════════

class SubscriptionLoader(QThread):
    """
    Загружает подписку из URL, парсит серверы и измеряет пинг параллельно.

    Сигналы:
      finished(sub_name, servers_list, userinfo | None)
      error(message)

    Каждый сервер в servers_list: {cc, flag, name, ping, _raw, _link}.
    """

    finished = pyqtSignal(str, list, object)
    error    = pyqtSignal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        if not _PARSER_OK:
            self.error.emit("Модуль parser недоступен")
            return

        try:
            links, userinfo = fetch_subscription(self._url)
        except Exception as e:
            self.error.emit(f"Ошибка загрузки: {e}")
            return

        # Название подписки из заголовка profile-title
        sub_name = (userinfo.get("title") or "") if userinfo else ""

        if not links:
            self.error.emit("Серверы не найдены. Проверьте ссылку подписки.")
            return

        # Парсим все ссылки
        parsed_pairs = [
            (lnk, info)
            for lnk in links
            if (info := parse_any_link(lnk)) is not None
        ]
        if not parsed_pairs:
            self.error.emit("Ни один сервер не удалось распознать.")
            return

        try:
            from core.ping_checker import PingChecker, format_ping
        except ImportError:
            # Fallback на старый метод если ping_checker недоступен
            logger.debug("ping_checker module not found, using fallback")
            import subprocess
            import socket
            import time
            import platform as _platform
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _ping_server_fallback(args):
                """Старый метод для обратной совместимости."""
                idx, host, port = args

                # TCP ping (более надёжен чем ICMP)
                try:
                    start = time.monotonic()
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3.0)  # Увеличен таймаут
                    result = sock.connect_ex((host, int(port)))
                    elapsed = int((time.monotonic() - start) * 1000)
                    sock.close()

                    if result == 0 and 0 < elapsed < 5000:
                        return idx, elapsed
                except:
                    pass

                return idx, None

            # Запуск fallback пинга
            tasks = [(i, info["host"], info["port"]) for i, (_, info) in enumerate(parsed_pairs)]
            ping_map: dict[int, int | None] = {i: None for i in range(len(parsed_pairs))}

            max_workers = min(15, len(tasks))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_ping_server_fallback, task): task[0] for task in tasks}
                for future in as_completed(futures):
                    try:
                        idx, ping_ms = future.result()
                        ping_map[idx] = ping_ms
                    except Exception as e:
                        logger.debug(f"Ping error: {e}")

        else:
            # ─── НОВЫЙ МЕТОД С PingChecker ───
            logger.debug(f"Starting TCP ping for {len(parsed_pairs)} servers...")

            # Создаём PingChecker с оптимальными настройками
            checker = PingChecker(
                timeout=3.5,  # Увеличенный таймаут для зарубежных серверов
                retries=1  # Одна попытка для скорости (можно увеличить до 2)
            )

            # Формируем список задач
            server_tasks = [(info["host"], info["port"]) for _, info in parsed_pairs]

            # Измеряем все серверы параллельно
            results = checker.measure_multiple(server_tasks)

            # Преобразуем результаты в формат {index: ping_ms}
            ping_map: dict[int, int | None] = {}
            for i, (host, port) in enumerate(server_tasks):
                ping_map[i] = results.get((host, port))

            # Статистика
            success_count = sum(1 for v in ping_map.values() if v is not None)
            logger.debug(f"Done: {success_count}/{len(ping_map)} servers responded")

            # Освобождаем ресурсы
            checker.cleanup()

        servers = []
        for i, (lnk, info) in enumerate(parsed_pairs):
            tag  = info.get("tag", "")
            cc   = tag[:2] if tag and len(tag) >= 2 else ""
            flag = get_flag_emoji(cc)
            servers.append({
                "cc":    cc.lower(),
                "flag":  flag,
                "name":  tag or info["host"],
                "ping":  ping_map.get(i),
                "_raw":  info,
                "_link": lnk,
            })

        # Если название не получили — берём из первого тега
        if not sub_name and servers:
            first_tag = servers[0].get("name", "")
            m = re.match(r"^([A-Za-zА-Яа-я]+)", first_tag)
            sub_name = m.group(1).upper() if m else "VPN"

        self.finished.emit(sub_name or "VPN", servers, userinfo)


# ══════════════════════════════════════════════════════════
#  ВОРКЕР — подключение / отключение VPN
# ══════════════════════════════════════════════════════════

class VpnConnectWorker(QThread):
    """
    Запускает или останавливает VPN (sing-box) в чистом TUN-режиме.

    Сигналы:
      success(True)   — подключение успешно.
      success(False)  — отключение завершено.
      error(message)  — ошибка при подключении.
    """

    success = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(
            self,
            connect: bool,
            server_info: dict,
            settings: dict,
            parent=None,
    ) -> None:
        super().__init__(parent)
        self._connect = connect
        self._server_info = server_info
        self._settings = settings
        self._runner_ref = None

    def set_runner(self, runner_container: list) -> None:
        """Передаёт контейнер [VPNRunner | None] для хранения экземпляра runner."""
        self._runner_ref = runner_container

    def run(self) -> None:
        if self._connect:
            try:
                from core.config_gen import (
                    generate_sing_box_config,
                    generate_xray_config,
                    save_config,
                    save_xray_config,
                )
                from core.runner import VPNRunner, XrayRunner
                import time

                app_list = (
                    self._settings.get("apps") or []
                    if self._settings.get("whitelist_enabled")
                    else None
                )
                transport = self._server_info.get('transport', 'tcp')
                use_xray = transport in ('xhttp', 'splithttp', 'httpupgrade')

                if use_xray:
                    config = generate_xray_config(self._server_info, app_whitelist=app_list)
                    save_xray_config(config)  # сохраняем в bin/xray/xray_config.json
                    runner = XrayRunner()
                else:
                    config = generate_sing_box_config(self._server_info, app_whitelist=app_list)
                    save_config(config)  # сохраняем в bin/config.json
                    runner = VPNRunner()
                self._runner_ref[0] = runner
                runner.start()
                time.sleep(1.5)

                if not runner.is_running():
                    self._runner_ref[0] = None
                    engine_name = "Xray" if use_xray else "sing-box"
                    self.error.emit(f"Ядро {engine_name} не запустилось.")
                    return

                self.success.emit(True)

            except Exception as e:
                if self._runner_ref and self._runner_ref[0]:
                    try:
                        self._runner_ref[0].stop()
                    except Exception:
                        pass
                    self._runner_ref[0] = None
                self.error.emit(str(e))
        else:
            try:
                import time
                if self._runner_ref and self._runner_ref[0]:
                    self._runner_ref[0].stop()
                    self._runner_ref[0] = None
                time.sleep(0.4)
                self.success.emit(False)
            except Exception as e:
                self.error.emit(str(e))


# ══════════════════════════════════════════════════════════
#  ДИАЛОГ — ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ
# ══════════════════════════════════════════════════════════

class DeleteConfirmDialog(QWidget):
    """
    Оверлей с fade-in: «Удалить подписку? [Отмена] [Удалить]».

    Сигналы:
      confirmed() — пользователь нажал «Удалить».
      cancelled() — пользователь нажал «Отмена» или кликнул вне карточки.
    """

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._opacity_eff = QGraphicsOpacityEffect(self)
        self._opacity_eff.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_eff)
        self._fade_val   = 0.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(12)
        self._fade_timer.timeout.connect(self._do_fade)
        self._fade_timer.start()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._card = GlassCard(radius=16, alpha=242)
        self._card.setFixedWidth(380)
        outer.addWidget(self._card, 0, Qt.AlignmentFlag.AlignCenter)

        vlay = QVBoxLayout(self._card)
        vlay.setContentsMargins(28, 24, 28, 24)
        vlay.setSpacing(14)

        title = QLabel("🗑  Удалить подписку?")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: rgba(232,226,255,240); background: transparent;")
        vlay.addWidget(title)

        hint = QLabel("Ссылка на подписку будет удалена.\nСписок серверов очистится.")
        hint.setFont(QFont("Segoe UI", 10))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(160,170,210,180); background: transparent;")
        vlay.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setMinimumHeight(40)
        btn_cancel.setFont(QFont("Segoe UI", 11))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(themed_btn_ss())
        btn_cancel.clicked.connect(self._cancel)

        btn_delete = QPushButton("Удалить")
        btn_delete.setMinimumHeight(40)
        btn_delete.setFont(QFont("Segoe UI", 11))
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete.setStyleSheet("""
            QPushButton {
                background: rgba(140,30,30,130);
                border: 1px solid rgba(220,80,80,140);
                border-radius: 10px;
                color: rgba(255,180,180,220);
            }
            QPushButton:hover {
                background: rgba(180,40,40,180);
                border-color: rgba(255,100,100,200);
                color: rgba(255,210,210,240);
            }
            QPushButton:pressed {
                background: rgba(200,50,50,210);
            }
        """)
        btn_delete.clicked.connect(self._confirm)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_delete)
        vlay.addLayout(btn_row)

    def _do_fade(self) -> None:
        self._fade_val = min(1.0, self._fade_val + 0.09)
        self._opacity_eff.setOpacity(self._fade_val)
        if self._fade_val >= 1.0:
            self._fade_timer.stop()
            self.setGraphicsEffect(None)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 2, 14, 205))

    def mousePressEvent(self, e) -> None:
        if not self._card.geometry().contains(e.pos()):
            self._cancel()
        else:
            super().mousePressEvent(e)

    def close_dialog(self) -> None:
        """Программное закрытие (например, при закрытии главного окна)."""
        self._cancel()

    def _confirm(self) -> None:
        self.confirmed.emit()
        self.hide()
        self.deleteLater()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()
        self.deleteLater()


# ══════════════════════════════════════════════════════════
#  ОВЕРЛЕЙ — ПРЕДУПРЕЖДЕНИЕ О АКТИВНОМ VPN
# ══════════════════════════════════════════════════════════

class VpnWarnOverlay(QWidget):
    """
    Немодальный оверлей «VPN активен — сначала отключитесь».
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(parent.rect() if parent else self.rect())

        self._opacity_eff = QGraphicsOpacityEffect(self)
        self._opacity_eff.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_eff)
        self._fade_val   = 0.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(12)
        self._fade_timer.timeout.connect(self._do_fade)
        self._fade_timer.start()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._card = GlassCard(radius=16, alpha=242)
        self._card.setFixedWidth(340)
        outer.addWidget(self._card, 0, Qt.AlignmentFlag.AlignCenter)

        vlay = QVBoxLayout(self._card)
        vlay.setContentsMargins(28, 22, 28, 22)
        vlay.setSpacing(10)

        title = QLabel("🔒  VPN активен")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: rgba(232,226,255,240); background: transparent;")
        vlay.addWidget(title)

        hint = QLabel("Сначала отключите VPN\nчтобы выполнить это действие.")
        hint.setFont(QFont("Segoe UI", 10))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(160,170,210,180); background: transparent;")
        vlay.addWidget(hint)

        btn_ok = QPushButton("Понятно")
        btn_ok.setMinimumHeight(38)
        btn_ok.setFont(QFont("Segoe UI", 11))
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setStyleSheet(themed_btn_ss())
        btn_ok.clicked.connect(self._close)
        vlay.addWidget(btn_ok)

    def _do_fade(self) -> None:
        self._fade_val = min(1.0, self._fade_val + 0.09)
        self._opacity_eff.setOpacity(self._fade_val)
        if self._fade_val >= 1.0:
            self._fade_timer.stop()
            self.setGraphicsEffect(None)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 2, 14, 180))

    def mousePressEvent(self, e) -> None:
        if not self._card.geometry().contains(e.pos()):
            self._close()
        else:
            super().mousePressEvent(e)

    def _close(self) -> None:
        self.hide()
        self.deleteLater()


# ══════════════════════════════════════════════════════════
#  ДИАЛОГ — ДОБАВИТЬ / ИЗМЕНИТЬ URL ПОДПИСКИ
# ══════════════════════════════════════════════════════════

class AddSubscriptionDialog(QWidget):
    """
    Оверлей с fade-in для ввода URL VPN-подписки.

    Сигналы:
      saved(url)  — пользователь сохранил URL.
      cancelled() — пользователь закрыл диалог без сохранения.
    """

    saved     = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, current_url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._opacity_eff = QGraphicsOpacityEffect(self)
        self._opacity_eff.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_eff)
        self._fade_val   = 0.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(12)
        self._fade_timer.timeout.connect(self._do_fade)
        self._fade_timer.start()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._card = GlassCard(radius=16, alpha=242)
        self._card.setFixedWidth(440)
        outer.addWidget(self._card, 0, Qt.AlignmentFlag.AlignCenter)

        vlay = QVBoxLayout(self._card)
        vlay.setContentsMargins(28, 24, 28, 24)
        vlay.setSpacing(14)

        title = QLabel("🔗  Подписка по ссылке")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color: rgba(232,226,255,240); background: transparent;")
        vlay.addWidget(title)

        hint = QLabel("Вставьте URL вашей VPN-подписки")
        hint.setFont(QFont("Segoe UI", 9))
        hint.setStyleSheet("color: rgba(160,170,210,160); background: transparent;")
        vlay.addWidget(hint)

        self._input = QLineEdit()
        self._input.setPlaceholderText("https://...")
        self._input.setText(current_url)
        self._input.setFont(QFont("Segoe UI", 10))
        self._input.setMinimumHeight(38)
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba({int(r*0.10)},{int(g*0.06)},{int(b*0.14)},160);
                border: 1px solid rgba({int(r*0.70)},{int(g*0.45)},{int(b*0.72)},120);
                border-radius: 8px;
                color: rgba(220,215,255,230);
                padding: 4px 12px;
                selection-background-color: rgba({int(r*0.60)},{int(g*0.35)},{int(b*0.62)},180);
            }}
            QLineEdit:focus {{
                border-color: rgba({int(r*0.95)},{int(g*0.65)},{int(b*0.95)},200);
            }}
        """)
        vlay.addWidget(self._input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setMinimumHeight(40)
        btn_cancel.setFont(QFont("Segoe UI", 11))
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet(themed_btn_ss())
        btn_cancel.clicked.connect(self._cancel)

        btn_save = QPushButton("Сохранить")
        btn_save.setMinimumHeight(40)
        btn_save.setFont(QFont("Segoe UI", 11))
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setStyleSheet(themed_strong_btn_ss())
        btn_save.clicked.connect(self._save)

        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        vlay.addLayout(btn_row)

        self._input.returnPressed.connect(self._save)

    def _do_fade(self) -> None:
        self._fade_val = min(1.0, self._fade_val + 0.09)
        self._opacity_eff.setOpacity(self._fade_val)
        if self._fade_val >= 1.0:
            self._fade_timer.stop()
            self.setGraphicsEffect(None)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 2, 14, 205))

    def mousePressEvent(self, e) -> None:
        if not self._card.geometry().contains(e.pos()):
            self._cancel()
        else:
            super().mousePressEvent(e)

    def close_dialog(self) -> None:
        """Программное закрытие (например, при закрытии главного окна)."""
        self._cancel()

    def _save(self) -> None:
        url = self._input.text().strip()
        cfg = AppSettings.load()
        cfg["subscription_url"] = url
        AppSettings.save(cfg)
        self.saved.emit(url)
        self.hide()
        self.deleteLater()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.hide()
        self.deleteLater()


# ══════════════════════════════════════════════════════════
#  ГЛАВНАЯ СТРАНИЦА СЕРВЕРОВ
# ══════════════════════════════════════════════════════════

class ServersPage(QWidget):
    """
    Страница с двумя колонками:
      • Левая  — список подписок (VpnSubscriptionCard) с кнопкой «+».
      • Правая — кнопка питания PowerButton, статус, таймер, тогл белого списка.

    Сигналы:
      open_whitelist()        — запрос перехода на страницу белых списков.
      vpn_state_changed(bool) — True = подключено, False = отключено.
    """

    open_whitelist    = pyqtSignal()
    vpn_state_changed = pyqtSignal(bool)

    _PANEL_W = 408   # ширина левой панели (px) — используется в двух виджетах

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── Состояние ────────────────────────────────────
        self._connected       = False
        self._connecting      = False
        self._loading_subscription = False
        self._seconds         = 0
        self._themed_widgets: list = []
        self._sub_cards:      list[VpnSubscriptionCard] = []
        self._loader:         SubscriptionLoader | None = None
        self._selected_server: dict | None = None
        self._vpn_worker:     VpnConnectWorker | None = None
        self._runner_container: list = [None]   # [0] = VPNRunner | None
        self._add_dlg:        AddSubscriptionDialog | None = None
        self._del_dlg:        DeleteConfirmDialog   | None = None

        # ── Корневой layout ──────────────────────────────
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Контент-виджет — блюрим при открытии диалогов
        self._content_widget = QWidget(self)
        self._content_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        root.addWidget(self._content_widget)

        inner = QHBoxLayout(self._content_widget)
        inner.setContentsMargins(10, 8, 10, 14)
        inner.setSpacing(10)

        # ── Левая колонка: список подписок ───────────────
        left = QVBoxLayout()
        left.setSpacing(8)
        left.setContentsMargins(0, 0, 0, 0)

        # Заголовок «СЕРВЕРЫ» + кнопка «+»
        hdr = GlassCard(radius=14, alpha=198)
        hdr.setFixedHeight(60)
        hdr.setFixedWidth(self._PANEL_W)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(19, 0, 14, 0)
        lbl = QLabel("СЕРВЕРЫ")
        lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl.setStyleSheet(
            "color: rgba(232,226,255,245); background: transparent; letter-spacing: 2px;")
        hl.addWidget(lbl)
        hl.addStretch()

        self._add_btn = QPushButton()
        self._add_btn.setFixedSize(34, 34)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setToolTip("Добавить VPN по ссылке")
        # Загружаем иконку plus.png
        plus_path = _os.path.join(_PROJECT_DIR, "assets", "app_images", "plus.png")
        if _os.path.isfile(plus_path):
            from ui.widgets import _tint_pixmap
            px = QPixmap(plus_path)
            if not px.isNull():
                white_px = _tint_pixmap(px, QColor(255, 255, 255))
                self._add_btn.setIcon(QIcon(white_px))
                self._add_btn.setIconSize(QSize(20, 20))
        else:
            self._add_btn.setText("+")
            self._add_btn.setFont(QFont("Segoe UI", 26, QFont.Weight.Medium))
        self._add_btn.setStyleSheet(themed_btn_ss() + """
            QPushButton {
                padding: 0px;
                text-align: center;
            }
        """)
        self._add_btn.clicked.connect(self._on_add_btn_clicked)
        self._themed_widgets.append(("add_btn", self._add_btn))
        hl.addWidget(self._add_btn)
        left.addWidget(hdr)

        # Прокручиваемый список подписок
        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_scroll.setStyleSheet("background: transparent; border: none;")
        outer_scroll.setViewportMargins(0, 0, 0, 14)
        outer_scroll.setFixedWidth(self._PANEL_W)
        outer_scroll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._themed_widgets.append(("outer_scroll", outer_scroll))

        self._subs_widget = QWidget()
        self._subs_widget.setObjectName("sc")
        self._subs_widget.setStyleSheet("background: transparent;")
        self._subs_layout = QVBoxLayout(self._subs_widget)
        self._subs_layout.setContentsMargins(0, 0, 0, 0)
        self._subs_layout.setSpacing(8)

        # Плейсхолдер до завершения загрузки
        self._placeholder = self._make_placeholder("Загрузка серверов…")
        self._subs_layout.addWidget(self._placeholder, 1)

        outer_scroll.setWidget(self._subs_widget)
        left.addWidget(outer_scroll, 1)
        inner.addLayout(left)

        # ── Правая колонка: кнопка питания + статус ──────
        right = QVBoxLayout()
        right.setSpacing(10)
        right.setContentsMargins(0, 0, 0, 0)

        vpn_wrap = QWidget()
        vpn_wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        vpn_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vl = QVBoxLayout(vpn_wrap)
        vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vl.setSpacing(8)

        # Кнопка — фиксированная позиция
        self._pwr = PowerButton()
        self._pwr.clicked.connect(self._toggle_vpn)
        vl.addStretch(1)
        vl.addWidget(self._pwr, 0, Qt.AlignmentFlag.AlignHCenter)
        vl.addSpacing(8)

        # Статус — фиксированная высота (всегда 2 строки)
        self._status_lbl = QLabel("Отключено\n")
        self._status_lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Medium))
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setFixedHeight(48)  # место под 2 строки всегда
        self._status_lbl.setStyleSheet(
            "color: rgba(220,215,255,200); background: transparent;")
        vl.addWidget(self._status_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        vl.addStretch(1)
        self._status_ss = "color: rgba(220,215,255,200); background: transparent;"

        right.addWidget(vpn_wrap, 1)

        # ── Нижняя панель: белый список ─────────
        bot_wrap = QWidget()
        bot_wrap.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        bot_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bot_outer = QHBoxLayout(bot_wrap)
        bot_outer.setContentsMargins(0, 0, 0, 14)
        bot_outer.setSpacing(0)
        bot_outer.addStretch()

        bot = GlassCard(radius=14, alpha=198)
        bot.setFixedSize(240, 80)
        bl = QVBoxLayout(bot)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(4)

        # Строка «Белый список» с тогглом
        wr = QHBoxLayout()
        wr.setSpacing(0)
        wl_lbl = QLabel("Белый список")
        wl_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Medium))
        wl_lbl.setStyleSheet("color: rgba(220,215,255,200); background: transparent;")
        wr.addWidget(wl_lbl)
        wr.addStretch()
        self._wl_toggle = ToggleSwitch(checked=AppSettings.get_whitelist_enabled())
        self._wl_toggle.toggled.connect(self._on_whitelist_toggle)
        wr.addWidget(self._wl_toggle)
        bl.addLayout(wr)

        self._wb = QPushButton("Настроить белые списки")
        self._wb.setFixedHeight(26)
        self._wb.setFont(QFont("Segoe UI", 9))
        self._wb.setCursor(Qt.CursorShape.PointingHandCursor)
        self._wb.setStyleSheet(themed_btn_ss())
        self._wb.clicked.connect(self._on_open_whitelist)
        self._themed_widgets.append(("wb", self._wb))
        bl.addWidget(self._wb)

        bot_outer.addWidget(bot)
        bot_outer.addStretch()
        right.addWidget(bot_wrap)
        inner.addLayout(right, 1)

        self._sec_timer = QTimer(self)
        self._sec_timer.timeout.connect(self._tick)
        ThemeManager.instance().connect_theme(self, self._refresh_theme)

        # Запускаем загрузку подписки после инициализации UI
        QTimer.singleShot(200, self._start_subscription_load)

    # ── Тема ─────────────────────────────────────────────

    def _refresh_theme(self, _c: QColor) -> None:
        for tag, w in self._themed_widgets:
            if tag == "add_btn":
                # Сохраняем стиль как при создании
                w.setStyleSheet(themed_btn_ss() + """
                    QPushButton {
                        padding: 0px;
                        text-align: center;
                    }
                """)
            elif tag == "outer_scroll":
                w.setStyleSheet("background: transparent; border: none;")
            elif tag == "wb":
                w.setStyleSheet(themed_btn_ss())

    # ── Выбор сервера ────────────────────────────────────

    def _on_server_selected(self, data: dict) -> None:
        self._selected_server = data
        self._update_pwr_state()

    # ── Загрузка подписки ────────────────────────────────

    def _make_placeholder(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Segoe UI", 12))
        lbl.setStyleSheet("color: rgba(160,170,210,160); background: transparent;")
        lbl.setMinimumHeight(80)
        return lbl

    def _update_pwr_state(self) -> None:
        blocked = self._selected_server is None or self._loading_subscription
        self._pwr.set_blocked(blocked)

        if not self._connected and self._selected_server is None and not self._loading_subscription:
            eff = QGraphicsOpacityEffect(self._pwr)
            eff.setOpacity(0.7)
            self._pwr.setGraphicsEffect(eff)
        else:
            self._pwr.setGraphicsEffect(None)
        self._pwr.update()

    def _start_subscription_load(self) -> None:
        self._selected_server = None
        self._loading_subscription = True
        self._update_pwr_state()

        cfg = AppSettings.load()
        url = cfg.get("subscription_url", "").strip()
        self._current_url = url

        if not url:
            self._set_placeholder("Нет ссылки подписки.\nУкажите URL в settings.json")
            return
        if not _PARSER_OK:
            self._set_placeholder("Модуль parser недоступен")
            return

        self._set_placeholder("⏳  Загрузка серверов…")
        self._loader = SubscriptionLoader(url, parent=self)
        self._loader.finished.connect(self._on_loaded)
        self._loader.error.connect(self._on_load_error)
        self._loader.start()

    def _set_placeholder(self, text: str) -> None:
        """Удаляет все карточки и показывает текстовый плейсхолдер."""
        while self._subs_layout.count():
            item = self._subs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._sub_cards.clear()
        self._placeholder = self._make_placeholder(text)
        self._subs_layout.addWidget(self._placeholder, 1)

    def _on_load_error(self, msg: str) -> None:
        self._loading_subscription = False
        self._set_placeholder(f"❌  {msg}")

    def _on_loaded(self, sub_name: str, servers: list, userinfo) -> None:
        """Получили список серверов — строим карточку подписки."""
        self._loading_subscription = False
        while self._subs_layout.count():
            item = self._subs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._sub_cards.clear()

        if not servers:
            ph = self._make_placeholder("Нет доступных серверов")
            self._subs_layout.addWidget(ph)
            self._subs_layout.addStretch()
            return

        # Формируем данные подписки из userinfo
        usage_gb  = 0.0
        limit_gb  = None
        expires   = "—"
        days_left = 0
        active    = True

        if userinfo:
            used_bytes  = userinfo.get("upload", 0) + userinfo.get("download", 0)
            total_bytes = userinfo.get("total", 0)
            usage_gb    = used_bytes / (1024 ** 3)
            limit_gb    = total_bytes / (1024 ** 3) if total_bytes > 0 else None
            exp_ts      = userinfo.get("expire", 0)
            if exp_ts:
                dt        = datetime.datetime.fromtimestamp(exp_ts)
                expires   = dt.strftime("%d.%m.%Y")
                days_left = max(0, (dt - datetime.datetime.now()).days)
                active    = days_left > 0

        sub = {
            "name":             sub_name,
            "usage_gb":         usage_gb,
            "limit_gb":         limit_gb,
            "active":           active,
            "expires":          expires,
            "days_left":        days_left,
            "servers":          servers,
            "subscription_url": getattr(self, "_current_url", ""),
        }

        sc = VpnSubscriptionCard(sub)
        sc.server_selected.connect(self._on_server_selected)
        sc.refresh_requested.connect(self._reload_subscription)
        sc.delete_requested.connect(self._on_delete_requested)
        if self._connected:
            sc.set_vpn_active(True)
        self._subs_layout.addWidget(sc, 1)
        self._sub_cards.append(sc)

        if self._selected_server is None and servers:
            self._selected_server = servers[0]
        self._update_pwr_state()

    def _reload_subscription(self) -> None:
        for sc in self._sub_cards:
            sc.set_refreshing(True)
        self._start_subscription_load()

    # ── VPN управление ───────────────────────────────────

    def _toggle_vpn(self) -> None:
        if self._selected_server is None or self._connecting:
            return
        if not self._connected:
            self._start_connect()
        else:
            self._start_disconnect()

    def _set_connecting_state(self, label: str) -> None:
        self._connecting = True
        # БЕЗ _update_pwr_state — не блокируем кнопку
        for sc in self._sub_cards:
            sc.set_vpn_active(True)
        self._status_lbl.setText(label + "\n")
        self._status_lbl.setStyleSheet(
            "color: rgba(220,215,255,200); background: transparent;")

    def _start_connect(self) -> None:
        self._set_connecting_state("Подключение…")
        settings = AppSettings.load()
        raw      = self._selected_server.get("_raw", self._selected_server)
        worker   = VpnConnectWorker(
            connect=True, server_info=raw, settings=settings, parent=self)
        worker.set_runner(self._runner_container)
        worker.success.connect(self._on_vpn_success)
        worker.error.connect(self._on_vpn_error)
        self._vpn_worker = worker
        worker.start()

    def _start_disconnect(self) -> None:
        self._set_connecting_state("Остановка…")
        self._sec_timer.stop()
        worker = VpnConnectWorker(
            connect=False, server_info={}, settings={}, parent=self)
        worker.set_runner(self._runner_container)
        worker.success.connect(self._on_vpn_success)
        worker.error.connect(self._on_vpn_error)
        self._vpn_worker = worker
        worker.start()

    def _on_vpn_success(self, connected: bool) -> None:
        self._connecting = False
        self._connected = connected
        self._pwr.set_connected(connected)
        self.vpn_state_changed.emit(connected)

        for sc in self._sub_cards:
            sc.set_vpn_active(connected)

        if connected:
            ac = ThemeManager.instance().color()
            r, g, b = ac.red(), ac.green(), ac.blue()
            color_ss = (
                f"color: rgba({min(255, int(r * 0.85 + 40))},{min(255, int(g * 0.75 + 50))},"
                f"{min(255, int(b * 0.80 + 30))},235); background: transparent;"
            )
            self._status_ss = color_ss
            self._status_lbl.setStyleSheet(color_ss)
            self._seconds = 0
            self._status_lbl.setText("Подключено\n00:00:00")
            self._sec_timer.start(1000)
        else:
            self._status_lbl.setText("Отключено\n")
            self._status_lbl.setStyleSheet(
                "color: rgba(220,215,255,200); background: transparent;")
            self._seconds = 0
            self._sec_timer.stop()

        self._update_pwr_state()

    def _on_vpn_error(self, msg: str) -> None:
        self._connecting = False
        self._connected  = False
        self._pwr.set_connected(False)
        self._status_lbl.setText(f"Ошибка: {msg}")
        self._status_lbl.setStyleSheet(
            "color: rgba(220,215,255,200); background: transparent;")
        self._sec_timer.stop()
        self._seconds = 0
        self.vpn_state_changed.emit(False)
        for sc in self._sub_cards:
            sc.set_vpn_active(False)
        self._update_pwr_state()

    def force_stop_vpn(self) -> None:
        """Вызывается при закрытии окна — останавливает VPN."""
        if self._runner_container[0]:
            try:
                self._runner_container[0].stop()
            except Exception:
                pass
            self._runner_container[0] = None

    # ── Таймер ───────────────────────────────────────────

    def _tick(self) -> None:
        self._seconds += 1
        h = self._seconds // 3600
        m = (self._seconds % 3600) // 60
        s = self._seconds % 60
        self._status_lbl.setText(f"Подключено\n{h:02d}:{m:02d}:{s:02d}")

    # ── Белый список ─────────────────────────────────────

    def _on_open_whitelist(self) -> None:
        if self._connected or self._connecting:
            self._vpn_lock_warning()
            return
        self.open_whitelist.emit()

    def _on_whitelist_toggle(self, enabled: bool) -> None:
        if self._connected or self._connecting:
            # Откатываем тогл обратно
            self._wl_toggle._checked = not enabled
            self._wl_toggle._pos    = 0.0 if enabled else 1.0
            self._wl_toggle._target = self._wl_toggle._pos
            self._wl_toggle.update()
            self._vpn_lock_warning()
            return
        AppSettings.set_whitelist_enabled(enabled)

    def _vpn_lock_warning(self) -> None:
        def _beep():
            try:
                import winsound
                winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()
        dlg = VpnWarnOverlay(parent=self.window())
        dlg.show()

    # ── Диалог добавления подписки ────────────────────────

    def _on_add_btn_clicked(self) -> None:
        if self._connected or self._connecting:
            self._vpn_lock_warning()
            return
        if self._add_dlg:
            return

        blur = QGraphicsBlurEffect(self._content_widget)
        blur.setBlurRadius(12)
        self._content_widget.setGraphicsEffect(blur)
        self._content_widget.setEnabled(False)

        current_url  = AppSettings.load().get("subscription_url", "")
        self._add_dlg = AddSubscriptionDialog(current_url=current_url, parent=self)
        self._add_dlg.setGeometry(0, 0, self.width(), self.height())
        self._add_dlg.saved.connect(self._on_url_saved)
        self._add_dlg.cancelled.connect(self._close_add_dialog)
        self._add_dlg.show()
        self._add_dlg.raise_()

    def _close_add_dialog(self) -> None:
        self._content_widget.setGraphicsEffect(None)
        self._content_widget.setEnabled(True)
        self._add_dlg = None

    def _on_url_saved(self, _url: str) -> None:
        self._close_add_dialog()
        self._start_subscription_load()

    # ── Диалог удаления подписки ──────────────────────────

    def _on_delete_requested(self) -> None:
        if self._del_dlg:
            return

        blur = QGraphicsBlurEffect(self._content_widget)
        blur.setBlurRadius(12)
        self._content_widget.setGraphicsEffect(blur)
        self._content_widget.setEnabled(False)

        self._del_dlg = DeleteConfirmDialog(parent=self)
        self._del_dlg.setGeometry(0, 0, self.width(), self.height())
        self._del_dlg.confirmed.connect(self._on_delete_confirmed)
        self._del_dlg.cancelled.connect(self._close_del_dialog)
        self._del_dlg.show()
        self._del_dlg.raise_()

    def _close_del_dialog(self) -> None:
        self._content_widget.setGraphicsEffect(None)
        self._content_widget.setEnabled(True)
        self._del_dlg = None

    def _on_delete_confirmed(self) -> None:
        cfg = AppSettings.load()
        cfg["subscription_url"] = ""
        AppSettings.save(cfg)
        self._close_del_dialog()
        # Сбрасываем выбранный сервер — без подписки подключение невозможно
        self._selected_server = None
        self._update_pwr_state()
        self._set_placeholder("Нет ссылки подписки.\nНажмите + чтобы добавить.")

    def close_dialog(self) -> None:
        """Закрывает все открытые диалоги — вызывается при закрытии главного окна."""
        if self._add_dlg:
            self._add_dlg.close_dialog()
        if self._del_dlg:
            self._del_dlg.close_dialog()

    # ── Resize ───────────────────────────────────────────

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._add_dlg:
            self._add_dlg.setGeometry(0, 0, self.width(), self.height())
        if self._del_dlg:
            self._del_dlg.setGeometry(0, 0, self.width(), self.height())