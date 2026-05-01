# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/settings_page.py — страница «Настройки».

Содержит:
  - SettingsPage — страница с двумя карточками:
      • «Фон приложения» — тоггл включения, кнопки выбора и сброса фона.
      • «Цвет акцента»   — пресеты, кастомный кружок, произвольный выбор цвета.

Зависимости:
    ui.theme   → ThemeManager, themed_btn_ss, themed_strong_btn_ss
    ui.widgets → GlassCard, ToggleSwitch
"""

import os
import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog,
    QColorDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from ui.theme import (
    ThemeManager,
    themed_btn_ss,
    themed_strong_btn_ss,
)
from ui.widgets import GlassCard, ToggleSwitch


# ══════════════════════════════════════════════════════════
#  СТРАНИЦА — НАСТРОЙКИ
# ══════════════════════════════════════════════════════════

class SettingsPage(QWidget):
    """
    Страница настроек: управление фоном и акцентным цветом.

    Сигналы:
        bg_changed(str)  — Пользователь выбрал новый фон (путь к файлу).
        bg_reset()       — Фон отключён тогглом (показать чистый градиент).
        bg_default()     — Сбросить фон к assets/pulsar.png.
        theme_changed(QColor) — Пользователь сменил акцентный цвет.
    """

    bg_changed    = pyqtSignal(str)
    bg_reset      = pyqtSignal()
    bg_default    = pyqtSignal()
    theme_changed = pyqtSignal(QColor)

    # Пресеты: (hex, подсказка, QColor) — синий первый (дефолт)
    _PRESET_DEFS = [
        ("#2d9cdb", "Синий",      QColor( 45, 156, 219)),
        ("#8250ff", "Фиолетовый", QColor(130,  80, 255)),
        ("#27ae60", "Зелёный",    QColor( 39, 174,  96)),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._last_bg_path: str  = ""    # последний пользовательский фон
        self._bg_enabled:   bool = True  # текущее состояние тоггла фона

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("Настройки")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: rgba(232,226,255,242); background: transparent;")
        root.addWidget(title)

        # Строка с двумя карточками рядом
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        cards_row.addWidget(self._build_bg_card())
        cards_row.addWidget(self._build_theme_card())
        root.addLayout(cards_row)
        root.addStretch()

        # Применяем стили сразу и при каждой смене темы
        ThemeManager.instance().connect_theme(self, self._refresh_btn_styles)
        self._refresh_btn_styles(ThemeManager.instance().color())

    # ── Строители карточек ────────────────────────────────

    def _build_bg_card(self) -> GlassCard:
        """Карточка «Фон приложения» с тогглом, кнопками выбора и сброса."""
        card = GlassCard(radius=14, alpha=194)
        card.setFixedHeight(210)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        # Заголовок + тоггл
        bg_header = QHBoxLayout()
        bg_header.setSpacing(6)
        self._sec_lbl_bg = QLabel("Фон приложения")
        self._sec_lbl_bg.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        bg_header.addWidget(self._sec_lbl_bg)
        bg_header.addStretch()
        self._bg_toggle = ToggleSwitch(checked=True)
        self._bg_toggle.toggled.connect(self._on_bg_toggle)
        bg_header.addWidget(self._bg_toggle)
        cl.addLayout(bg_header)

        self._bg_btn = QPushButton("🖼   Изменить фон")
        self._bg_btn.setFixedHeight(40)
        self._bg_btn.setFont(QFont("Segoe UI", 12))
        self._bg_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bg_btn.clicked.connect(self._pick)
        cl.addWidget(self._bg_btn)

        self._reset_btn = QPushButton("↺   Сбросить фон (по умолчанию)")
        self._reset_btn.setFixedHeight(32)
        self._reset_btn.setFont(QFont("Segoe UI", 11))
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.clicked.connect(self._on_reset_default)
        cl.addWidget(self._reset_btn)

        cl.addStretch()
        return card

    def _build_theme_card(self) -> GlassCard:
        """Карточка «Цвет акцента» с пресетами и произвольным выбором."""
        card = GlassCard(radius=14, alpha=194)
        card.setFixedHeight(210)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        self._th_lbl = QLabel("Цвет акцента")
        self._th_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        cl.addWidget(self._th_lbl)

        # Кружки пресетов + кастомный
        presets_row = QHBoxLayout()
        presets_row.setSpacing(8)
        self._preset_btns: list[tuple[QPushButton, QColor | None]] = []
        self._custom_color: QColor = QColor(ThemeManager.instance().color())

        for _hex, tip, col in self._PRESET_DEFS:
            pb = QPushButton()
            pb.setFixedSize(34, 34)
            pb.setToolTip(tip)
            pb.setCursor(Qt.CursorShape.PointingHandCursor)
            pb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            pb.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            pb.clicked.connect(lambda _c=False, c=col: self._apply_theme(c, preset=True))
            presets_row.addWidget(pb)
            self._preset_btns.append((pb, col))

        # Кастомный кружок — последний слот
        self._custom_btn = QPushButton()
        self._custom_btn.setFixedSize(34, 34)
        self._custom_btn.setToolTip("Кастомный")
        self._custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._custom_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._custom_btn.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._custom_btn.clicked.connect(self._apply_custom_stored)
        presets_row.addWidget(self._custom_btn)
        self._preset_btns.append((self._custom_btn, None))   # None = кастомный слот

        presets_row.addStretch()
        cl.addLayout(presets_row)

        self._pick_btn = QPushButton("🎨   Свой цвет…")
        self._pick_btn.setFixedHeight(34)
        self._pick_btn.setFont(QFont("Segoe UI", 12))
        self._pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pick_btn.clicked.connect(self._pick_color)
        cl.addWidget(self._pick_btn)

        self._reset_theme_btn = QPushButton("↺   Сбросить цвет по умолчанию")
        self._reset_theme_btn.setFixedHeight(32)
        self._reset_theme_btn.setFont(QFont("Segoe UI", 11))
        self._reset_theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_theme_btn.setToolTip("Сбросить цвет темы (синий)")
        self._reset_theme_btn.clicked.connect(
            lambda: self._apply_theme(QColor(45, 156, 219), preset=True)
        )
        cl.addWidget(self._reset_theme_btn)

        cl.addStretch()
        return card

    # ── Обработчики фона ──────────────────────────────────

    def _on_bg_toggle(self, enabled: bool) -> None:
        """Тоггл фона: включить/выключить фоновое изображение."""
        self._bg_enabled = enabled
        if enabled:
            # Восстанавливаем последний пользовательский фон или ставим дефолт
            if self._last_bg_path and os.path.isfile(self._last_bg_path):
                self.bg_changed.emit(self._last_bg_path)
            else:
                self.bg_default.emit()
        else:
            self.bg_reset.emit()

    def _on_reset_default(self) -> None:
        """Кнопка «Сбросить фон» — устанавливает assets/pulsar.png."""
        self._last_bg_path = ""
        self.bg_default.emit()

    def _pick(self) -> None:
        """Открывает диалог выбора изображения и копирует его в assets/app_images/."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выбрать фоновое изображение", "",
            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if not path:
            return

        dest_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "app_images"
        )
        os.makedirs(dest_dir, exist_ok=True)
        fname     = os.path.basename(path)
        dest_path = os.path.join(dest_dir, fname)
        try:
            if os.path.abspath(path) != os.path.abspath(dest_path):
                shutil.copy2(path, dest_path)
            path = dest_path
        except Exception as e:
            print(f"[SettingsPage._pick] Не удалось скопировать фон: {e}")

        self._last_bg_path = path
        if self._bg_enabled:
            self.bg_changed.emit(path)

    # ── Обработчики темы ──────────────────────────────────

    def _pick_color(self) -> None:
        """Открывает диалог выбора произвольного цвета акцента."""
        c = QColorDialog.getColor(self._custom_color, self, "Выбрать цвет акцента")
        if c.isValid():
            self._custom_color = c
            self._apply_theme(c, preset=False)

    def _apply_custom_stored(self) -> None:
        """Применяет сохранённый кастомный цвет по клику на кружок."""
        self._apply_theme(self._custom_color, preset=False)

    def _apply_theme(self, c: QColor, preset: bool = True) -> None:
        """Применяет цвет темы, сохраняет кастомный цвет и уведомляет подписчиков."""
        if not preset:
            self._custom_color = c
        ThemeManager.instance().set_color(c)
        self.theme_changed.emit(c)
        self._refresh_preset_selection(c)

    # ── Стили (пересчитываются при каждой смене темы) ────

    def _refresh_btn_styles(self, c: QColor) -> None:
        """Обновляет стили всех кнопок и заголовков карточек под текущую тему."""
        self._bg_btn.setStyleSheet(
            themed_strong_btn_ss("text-align: left; padding-left: 14px;")
        )
        self._reset_btn.setStyleSheet(
            themed_btn_ss("text-align: left; padding-left: 12px;")
        )
        self._pick_btn.setStyleSheet(
            themed_btn_ss("text-align: left; padding-left: 12px;")
        )
        self._reset_theme_btn.setStyleSheet(
            themed_btn_ss("text-align: left; padding-left: 12px;")
        )
        self._sec_lbl_bg.setStyleSheet("color: rgba(255,255,255,220); background: transparent;")
        self._th_lbl.setStyleSheet("color: rgba(255,255,255,220); background: transparent;")
        self._refresh_preset_selection(c)

    def _refresh_preset_selection(self, _active: QColor) -> None:
        """Перерисовывает обводки кружков пресетов: активный — с белой рамкой."""
        ac = ThemeManager.instance().color()

        # Определяем, какой пресет совпадает с текущим цветом
        active_idx: int | None = None
        for i, (pb, col) in enumerate(self._preset_btns):
            if col is None:
                continue
            if col.red() == ac.red() and col.green() == ac.green() and col.blue() == ac.blue():
                active_idx = i
                break

        is_custom_active = (active_idx is None)

        for i, (pb, col) in enumerate(self._preset_btns):
            if col is None:
                # Кастомный слот — всегда показывает _custom_color
                cc      = self._custom_color
                is_sel  = is_custom_active
                hex_col = cc.name()
            else:
                is_sel  = (i == active_idx)
                hex_col = col.name()

            if is_sel:
                pb.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {hex_col};
                        border-radius: 17px;
                        border: 3px solid rgba(255,255,255,220);
                        outline: none;
                        padding: 0px;
                    }}
                    QPushButton:hover  {{ border: 3px solid rgba(255,255,255,255); }}
                    QPushButton:pressed {{ border: 3px solid rgba(255,255,255,200); }}
                """)
            else:
                pb.setStyleSheet(f"""
                    QPushButton {{
                        background-color: {hex_col};
                        border-radius: 17px;
                        border: 3px solid transparent;
                        outline: none;
                        padding: 0px;
                    }}
                    QPushButton:hover  {{ border: 3px solid rgba(255,255,255,180); }}
                    QPushButton:pressed {{ border: 3px solid rgba(255,255,255,220); }}
                """)