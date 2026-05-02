# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/info_page.py — страница «О приложении».

Содержит:
  - InfoPage — четыре GlassCard в сетке 2×2 внутри QScrollArea,
    карточки не сжимаются при уменьшении окна — список скроллится вниз.
    Внизу (вне зоны скролла) — строка лицензии и команды Pulsar VPN Team.
    Цвета строк меняются вместе с темой.

Зависимости:
    ui.theme   → ThemeManager, scrollbar_ss
    ui.widgets → GlassCard
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import ThemeManager, scrollbar_ss
from ui.widgets import GlassCard
import webbrowser


# ══════════════════════════════════════════════════════════
#  СТРАНИЦА — О ПРИЛОЖЕНИИ
# ══════════════════════════════════════════════════════════

_CARD_ROWS_CLIENT: list[tuple[str, str]] = [
    ("Версия",        "Beta 1.3.0"),
    ("Платформа",     "Windows 10 / 11 (x64)"),
    ("Интерфейс",     "PyQt6 + Python 3.12"),
    ("Архитектура",   "64-bit (x86_64)"),
    ("Конфиг-формат", "JSON (sing-box + Xray)"),
    ("Автозапуск",    "Через реестр Windows"),
]

_CARD_ROWS_TUNNEL: list[tuple[str, str]] = [
    ("Ядро",           "sing-box 1.12.25 + Xray 26.2.6"),
    ("Режим",          "TUN + гибридный движок"),
    ("Протоколы",      "VLESS · VMess · Trojan · SS"),
    ("Транспорт",      "TCP · WebSocket · gRPC · HTTP · XHTTP"),
    ("TLS / REALITY",  "uTLS fingerprint (Chrome/FF/Edge)"),
    ("DNS",            "UDP · 8.8.8.8 / 8.8.4.4"),
]

_CARD_ROWS_SECURITY: list[tuple[str, str]] = [
    ("Шифрование",  "AES-128-GCM · ChaCha20-Poly1305"),
    ("TLS версия",  "TLS 1.2 / TLS 1.3"),
    ("REALITY",     "X25519 · уникальный short ID"),
    ("DNS-утечки",  "Защита через hijack-dns"),
    ("IPv6-утечки", "Отключены при подключении"),
    ("Kill Switch", "В разработке (upcoming)"),
]

_CARD_ROWS_DEV: list[tuple[str, str]] = [
    ("Команда",      "Pulsar VPN Team"),
    ("Статус",       "Beta — активная разработка"),
    ("Поддержка",    "Telegram: @ggoktay"),
    ("Исходный код", "GitHub · GPL-3.0 (open source)"),
    ("sing-box",     "© SagerNet (GPL-3.0)"),
    ("Xray",         "© Project X (MPL-2.0)"),
]

# ── Данные для карточки релиз-нотов ─────────────────────

_RELEASE_NOTES_TITLE = "Что нового в Beta 1.3.0"

# Левая колонка: исправления
_FIXES = [
    "Новая система измерения пинга (ICMP + TCP fallback)",
    "Парсинг русского вывода ping (кодировка CP866)",
    "Цветовая индикация пинга: зелёный/жёлтый/оранжевый/красный",
    "Кнопка питания: курсор и hover только по кругу",
    "Блокировка кнопки при загрузке серверов",
    "Иконка питания синхронизирована по цвету с кругом",
    "Кнопки управления заменены на PNG-иконки (белые)",
    "Таймер и статус объединены в один QLabel",
]

# Правая колонка: улучшения
_IMPROVEMENTS = [
    "Кнопки тайтлбара в цвете темы (приглушённые тона)",
    "Крестик: тонкий, подсветка красным при наведении",
    "Квадрат разворота: увеличен до 18px",
    "Кнопка «Настроить белые списки»: +6px по высоте",
    "Фон star.png (пульсар) позади кнопки питания",
    "Сохранение whitelist-данных между обновлениями",
    "Инсталлер: бэкап settings.json и apps.json при обновлении",
    "Повторный запуск exe восстанавливает окно из трея",
]

# Нижняя секция: примечания + ссылка
_NOTES = [
    "XHTTP/SplitHTTP серверы — в активной доработке (Xray TUN)",
    "Приложение на стадии бета-тестирования",
]

_GITHUB_LINK = "github.com/oktaygg/Pulsar-VPN-Client/releases"


class InfoPage(QWidget):
    """
    Страница с релиз-нотами и четырьмя информационными карточками (2×2).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Хранилища меток для bulk-перекраски
        self._lbl_refs: list[QLabel] = []
        self._val_refs: list[QLabel] = []

        # Корневой лэйаут: скролл-зона + прижатый футер
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_scroll_area(), stretch=1)
        root.addWidget(self._build_footer())

        # Применяем тему сразу и при каждой смене
        self._retheme(ThemeManager.instance().color())
        ThemeManager.instance().connect_theme(self, self._retheme)

    # ── Строитель зоны прокрутки ───────────────────────────

    def _build_scroll_area(self) -> QScrollArea:
        """Создаёт QScrollArea с релиз-нотами и карточками."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        scroll.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        scroll.setStyleSheet(
            scrollbar_ss() + "QScrollArea { background: transparent; }"
        )
        self._scroll = scroll

        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        content.setStyleSheet("background: transparent;")
        content.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        cl = QVBoxLayout(content)
        cl.setContentsMargins(18, 14, 18, 10)
        cl.setSpacing(14)
        cl.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Заголовок страницы
        title = QLabel("О приложении")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet(
            "color: rgba(232,226,255,242); background: transparent;"
        )
        cl.addWidget(title)

        # ── Карточка с релиз-нотами ──────────────────────────
        cl.addWidget(self._build_release_notes_card())

        # Сетка 2×2: верхний ряд
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(
            self._build_card("Pulsar VPN Client", _CARD_ROWS_CLIENT)
        )
        row1.addWidget(
            self._build_card("Туннельное ядро", _CARD_ROWS_TUNNEL)
        )
        cl.addLayout(row1)

        # Сетка 2×2: нижний ряд
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        row2.addWidget(
            self._build_card("Безопасность", _CARD_ROWS_SECURITY)
        )
        row2.addWidget(
            self._build_card("Разработчик", _CARD_ROWS_DEV)
        )
        cl.addLayout(row2)

        cl.addStretch()

        scroll.setWidget(content)
        return scroll

    # ── Строитель карточки с релиз-нотами ──────────────────

    def _build_release_notes_card(self) -> GlassCard:
        """
        Карточка с релиз-нотами: две колонки сверху (исправления / улучшения),
        под ними примечания и кнопка для скачивания последней версии с GitHub.
        """
        card = GlassCard(radius=14, alpha=194)
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        outer = QVBoxLayout(card)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)

        # Заголовок
        head = QLabel(_RELEASE_NOTES_TITLE)
        head.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        head.setStyleSheet(
            "color: rgba(232,226,255,245); background: transparent;"
        )
        outer.addWidget(head)

        # Разделитель
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background: rgba(255,255,255,20); border: none;")
        div.setFixedHeight(1)
        outer.addWidget(div)

        # ── Верхняя часть: две колонки ─────────────────────
        cols = QHBoxLayout()
        cols.setSpacing(20)

        # Левая колонка: исправления
        fixes_widget = self._build_notes_column("🔧 Исправления", _FIXES)
        cols.addWidget(fixes_widget, 1)

        # Правая колонка: улучшения
        improvements_widget = self._build_notes_column("⚡ Улучшения", _IMPROVEMENTS)
        cols.addWidget(improvements_widget, 1)

        outer.addLayout(cols)

        # Разделитель перед примечаниями
        div2 = QFrame()
        div2.setFrameShape(QFrame.Shape.HLine)
        div2.setStyleSheet("background: rgba(255,255,255,14); border: none;")
        div2.setFixedHeight(1)
        outer.addWidget(div2)

        # ── Примечания (одна строка) ───────────────────────
        notes_label = QLabel("💡 " + " · ".join(_NOTES))
        notes_label.setFont(QFont("Segoe UI", 10))
        notes_label.setWordWrap(True)
        notes_label.setStyleSheet(
            "color: rgba(180,190,220,180); background: transparent;"
        )
        outer.addWidget(notes_label)

        # ── Кнопка для скачивания последней версии ─────────
        self._download_btn = QPushButton("Скачать последнюю версию")
        self._download_btn.setFont(QFont("Segoe UI", 11))
        self._download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_btn.setStyleSheet(
            "QPushButton {"
            "  background: transparent;"
            "  border: 1px solid rgba(100,160,220,130);"
            "  border-radius: 8px;"
            "  color: rgba(140,170,220,230);"
            "  padding: 6px 16px;"
            "  text-align: center;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(100,160,220,40);"
            "  border-color: rgba(140,200,255,200);"
            "  color: rgba(200,220,255,250);"
            "}"
        )
        self._download_btn.clicked.connect(
            lambda: webbrowser.open(f"https://{_GITHUB_LINK}")
        )
        outer.addWidget(self._download_btn, 0, Qt.AlignmentFlag.AlignLeft)

        return card

    def _build_notes_column(self, title: str, items: list[str]) -> QWidget:
        """Создаёт вертикальную колонку с заголовком и списком пунктов."""
        widget = QWidget()
        widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Заголовок секции
        header = QLabel(title)
        header.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        header.setStyleSheet(
            "color: rgba(232,226,255,230); background: transparent;"
        )
        layout.addWidget(header)

        # Пункты списка
        for item in items:
            lbl = QLabel(f"• {item}")
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                "color: rgba(190,200,220,195); background: transparent;"
            )
            layout.addWidget(lbl)

        layout.addStretch()
        return widget

    # ── Строитель карточки ─────────────────────────────────

    def _build_card(
        self,
        heading: str,
        rows: list[tuple[str, str]],
    ) -> GlassCard:
        """
        GlassCard с заголовком, разделителем и строками «метка — значение».
        Карточка растягивается пополам по горизонтали, высота фиксированная.
        """
        card = GlassCard(radius=14, alpha=194)
        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 18, 22, 18)
        cl.setSpacing(10)

        # Заголовок карточки
        head_lbl = QLabel(heading)
        head_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        head_lbl.setStyleSheet(
            "color: rgba(232,226,255,245); background: transparent;"
        )
        cl.addWidget(head_lbl)

        # Разделитель
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background: rgba(255,255,255,20); border: none;")
        div.setFixedHeight(1)
        cl.addWidget(div)

        # Строки метка–значение
        for lbl_text, val_text in rows:
            row = QHBoxLayout()
            row.setSpacing(10)

            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )
            self._lbl_refs.append(lbl)

            val = QLabel(val_text)
            val.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
            val.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            val.setSizePolicy(
                QSizePolicy.Policy.Preferred,
                QSizePolicy.Policy.Fixed,
            )
            self._val_refs.append(val)

            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            cl.addLayout(row)

        return card

    # ── Строитель футера ───────────────────────────────────

    def _build_footer(self) -> QWidget:
        """
        Виджет с линией-разделителем и тремя строками:
        """
        widget = QWidget()
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 6, 18, 10)
        layout.setSpacing(3)

        # Тонкая линия сверху
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background: rgba(255,255,255,14); border: none;")
        div.setFixedHeight(1)
        layout.addWidget(div)

        # Строка 1: тип лицензии
        lic_line1 = QLabel(
            "Данное приложение распространяется с открытым исходным кодом "
            "по лицензии GNU GPL-3.0. Xray — под лицензией MPL-2.0."
        )
        lic_line1.setFont(QFont("Segoe UI", 9))
        lic_line1.setWordWrap(True)
        layout.addWidget(lic_line1)

        # Строка 2: sing-box на отдельной строке
        lic_line2 = QLabel(
            "Используемые ядра sing-box и Xray распространяются под свободными лицензиями."
        )
        lic_line2.setFont(QFont("Segoe UI", 9))
        lic_line2.setWordWrap(True)
        layout.addWidget(lic_line2)

        # Строка 3: авторство
        team_lbl = QLabel("© 2026 Pulsar VPN Team  ·  Beta Release")
        team_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        layout.addWidget(team_lbl)

        # Сохраняем ссылки для перекраски
        self._footer_lic1 = lic_line1
        self._footer_lic2 = lic_line2
        self._footer_team = team_lbl

        return widget

    # ── Тема ───────────────────────────────────────────────

    def _retheme(self, c: QColor) -> None:
        """Пересчитывает цвета всех меток и футера под новый акцент."""
        r, g, b = c.red(), c.green(), c.blue()

        lbl_ss = (
            f"color: rgba("
            f"{max(80, int(r * 0.55 + 40))},"
            f"{max(80, int(g * 0.42 + 50))},"
            f"{max(100, int(b * 0.55 + 60))},"
            f"175); background: transparent;"
        )
        val_ss = (
            f"color: rgba("
            f"{min(255, int(r * 0.75 + 70))},"
            f"{min(255, int(g * 0.68 + 80))},"
            f"{min(255, int(b * 0.65 + 90))},"
            f"230); background: transparent;"
        )

        for lbl in self._lbl_refs:
            lbl.setStyleSheet(lbl_ss)
        for val in self._val_refs:
            val.setStyleSheet(val_ss)

        # Скроллбар перекрашиваем вместе с темой
        self._scroll.setStyleSheet(
            scrollbar_ss() + "QScrollArea { background: transparent; }"
        )

        # Футер
        footer_dim = (
            f"color: rgba("
            f"{max(120, int(r * 0.55 + 60))},"
            f"{max(110, int(g * 0.48 + 55))},"
            f"{max(140, int(b * 0.55 + 70))},"
            f"130); background: transparent;"
        )
        footer_team_ss = (
            f"color: rgba("
            f"{max(140, int(r * 0.60 + 65))},"
            f"{max(130, int(g * 0.52 + 60))},"
            f"{max(160, int(b * 0.58 + 75))},"
            f"165); background: transparent;"
        )

        self._footer_lic1.setStyleSheet(footer_dim)
        self._footer_lic2.setStyleSheet(footer_dim)
        self._footer_team.setStyleSheet(footer_team_ss)