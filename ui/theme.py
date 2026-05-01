# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/theme.py — единый источник цветов и стилей.

Содержит:
  - ThemeManager  — синглтон, хранит акцентный цвет и рассылает сигнал theme_changed.
  - Глобальные цветовые константы (ACCENT, PANEL_BORDER и т.д.),
    которые ThemeManager пересчитывает при каждой смене темы.
  - Функции-генераторы стилей (themed_btn_ss, scrollbar_ss и др.),
    которые читают текущий цвет из ThemeManager и возвращают готовый QSS.

Все остальные модули ui/* импортируют отсюда — этот файл ни от кого не зависит.
"""

import weakref

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QColor

try:
    from PyQt6 import sip as _sip
except ImportError:
    _sip = None


# ══════════════════════════════════════════════════════════
#  МЕНЕДЖЕР ТЕМЫ
# ══════════════════════════════════════════════════════════

class ThemeManager(QObject):
    """
    Синглтон. Хранит текущий акцентный цвет и рассылает сигнал
    theme_changed(QColor) всем подписчикам при его смене.

    Использование:
        ThemeManager.instance().set_color(QColor("#ff6600"))
        ThemeManager.instance().connect_theme(widget, widget._on_theme)
    """

    theme_changed = pyqtSignal(QColor)

    _instance: "ThemeManager | None" = None

    # ── Синглтон ─────────────────────────────────────────
    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(45, 156, 219)   # дефолт: синий

    # ── Публичный API ─────────────────────────────────────
    def color(self) -> QColor:
        """Возвращает текущий акцентный цвет."""
        return self._color

    def set_color(self, c: QColor) -> None:
        """Устанавливает новый акцент, пересчитывает глобальные константы
        и уведомляет всех подписчиков через сигнал theme_changed."""
        self._color = c
        _update_globals(c)
        self.theme_changed.emit(c)

    def connect_theme(self, receiver: QObject, slot) -> None:
        """
        Безопасное подключение к theme_changed через weakref-обёртку.

        Стандартный connect хранит сильную ссылку на slot/receiver,
        что мешает сборщику мусора удалять уничтоженные виджеты.
        Эта обёртка молча игнорирует вызов, если receiver уже удалён.
        """
        try:
            ref = weakref.ref(receiver)
        except TypeError:
            # Некоторые C-расширения не поддерживают weakref — подключаем напрямую.
            self.theme_changed.connect(slot)
            return

        def _safe_slot(color: QColor, _ref=ref, _slot=slot) -> None:
            obj = _ref()
            if obj is None:
                return
            if _sip is not None:
                try:
                    if _sip.isdeleted(obj):
                        return
                except (RuntimeError, TypeError):
                    pass
            try:
                _slot(color)
            except RuntimeError:
                # Виджет уже уничтожен на стороне C++ — игнорируем.
                pass

        self.theme_changed.connect(_safe_slot)


# ══════════════════════════════════════════════════════════
#  ГЛОБАЛЬНЫЕ ЦВЕТОВЫЕ КОНСТАНТЫ
#  Мутируются _update_globals() при каждой смене темы.
#  Инициализированы под дефолтный синий цвет (#2d9cdb).
# ══════════════════════════════════════════════════════════

# Базовый акцентный цвет
ACCENT       = QColor( 45, 156, 219)

# Граница стеклянных панелей — тот же оттенок, полупрозрачный
PANEL_BORDER = QColor( 38, 132, 186,  68)

# Подсветка при наведении на строку
ITEM_HOVER   = QColor( 28,  96, 140,  70)

# Градиент выделенной строки: левый и правый край
ITEM_SEL_L   = QColor( 36, 120, 180, 130)
ITEM_SEL_R   = QColor( 16,  56,  96,  50)

# Основной и вторичный текст (вторичный мутирует, основной — нет)
TEXT_PRI     = QColor(225, 235, 255)   # белёсый, не меняется
TEXT_SEC     = QColor(115, 148, 175)   # мутирует вместе с темой

# Индикатор «подключено»
STATUS_ON    = QColor( 70, 220, 130)

# Строка стиля кнопок — используется как fallback (обновляется в _update_globals)
BTN_SS = """
QPushButton {{
    background: rgba(18,62,108,122);
    border: 1px solid rgba(40,100,198,112);
    border-radius: 7px;
    color: rgba(150,192,240,192);
    {extra}
}}
QPushButton:hover {{
    background: rgba(28,88,148,170);
    border-color: rgba(60,148,240,170);
    color: rgba(194,228,254,230);
}}
"""


def _update_globals(c: QColor) -> None:
    """
    Пересчитывает все глобальные цветовые константы под новый оттенок.
    Вызывается автоматически из ThemeManager.set_color().
    """
    global ACCENT, PANEL_BORDER, ITEM_HOVER, ITEM_SEL_L, ITEM_SEL_R, TEXT_SEC, BTN_SS
    r, g, b = c.red(), c.green(), c.blue()

    ACCENT       = c
    PANEL_BORDER = QColor(int(r * 0.85), int(g * 0.65), int(b * 0.87), 68)
    ITEM_HOVER   = QColor(int(r * 0.62), int(g * 0.45), int(b * 0.63), 70)
    ITEM_SEL_L   = QColor(int(r * 0.77), int(g * 0.59), int(b * 0.82), 130)
    ITEM_SEL_R   = QColor(int(r * 0.42), int(g * 0.25), int(b * 0.43), 50)
    TEXT_SEC     = QColor(int(r * 0.60 + 60), int(g * 0.45 + 60), int(b * 0.50 + 80))

    BTN_SS = f"""
QPushButton {{{{
    background: rgba({int(r*0.40)},{int(g*0.23)},{int(b*0.42)},122);
    border: 1px solid rgba({int(r*0.75)},{int(g*0.49)},{int(b*0.78)},112);
    border-radius: 7px;
    color: rgba({int(r*0.83+40)},{int(g*0.68+50)},{int(b*0.80+40)},192);
    {{extra}}
}}
QPushButton:hover {{{{
    background: rgba({int(r*0.55)},{int(g*0.34)},{int(b*0.58)},170);
    border-color: rgba({int(r*0.98)},{int(g*0.69)},{int(b*0.94)},170);
    color: rgba({min(255,int(r*0.93+40))},{min(255,int(g*0.80+50))},{min(255,int(b*0.90+40))},230);
}}
}}
"""


# ══════════════════════════════════════════════════════════
#  ФУНКЦИИ-ГЕНЕРАТОРЫ СТИЛЕЙ QSS
#  Каждая функция читает текущий цвет из ThemeManager
#  и возвращает готовую строку стиля.
# ══════════════════════════════════════════════════════════

def themed_btn_ss(
    extra: str = "",
    height: int = 0,
    radius: int = 7,
    strong: bool = False,
) -> str:
    """
    Генерирует QSS для обычной кнопки в цвете текущей темы.

    Args:
        extra:  Дополнительные CSS-правила, вставляемые в блок QPushButton{}.
        height: Если > 0, добавляет «height: Npx;» в стиль.
        radius: Радиус скругления углов в пикселях.
        strong: Увеличивает яркость фона кнопки примерно на 25%.
    """
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()
    mul = 1.25 if strong else 1.0
    h_rule = f"height: {height}px;" if height else ""
    return f"""
QPushButton {{
    background: rgba({int(r*0.40*mul)},{int(g*0.23*mul)},{int(b*0.42*mul)},130);
    border: 1px solid rgba({int(r*0.75)},{int(g*0.49)},{int(b*0.78)},120);
    border-radius: {radius}px;
    color: rgba({min(255,int(r*0.83+40))},{min(255,int(g*0.68+50))},{min(255,int(b*0.80+40))},200);
    {extra} {h_rule}
}}
QPushButton:hover {{
    background: rgba({int(r*0.60*mul)},{int(g*0.36*mul)},{int(b*0.62*mul)},180);
    border-color: rgba({int(r*0.98)},{int(g*0.69)},{int(b*0.95)},180);
    color: rgba({min(255,int(r*0.93+40))},{min(255,int(g*0.80+50))},{min(255,int(b*0.90+40))},240);
}}
QPushButton:pressed {{
    background: rgba({int(r*0.70*mul)},{int(g*0.42*mul)},{int(b*0.72*mul)},210);
}}
"""


def themed_strong_btn_ss(extra: str = "", radius: int = 10) -> str:
    """
    Более яркая акцентная кнопка (например, «Изменить фон»).
    Отличается от themed_btn_ss более насыщенным фоном и белым текстом при hover.
    """
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()
    return f"""
QPushButton {{
    background: rgba({int(r*0.60)},{int(g*0.34)},{int(b*0.63)},150);
    border: 1px solid rgba({int(r*0.91)},{int(g*0.60)},{int(b*0.89)},170);
    border-radius: {radius}px;
    color: rgba({min(255,int(r*0.80+40))},{min(255,int(g*0.73+50))},{min(255,int(b*0.80+20))},230);
    {extra}
}}
QPushButton:hover {{
    background: rgba({int(r*0.76)},{int(g*0.45)},{int(b*0.75)},200);
    border-color: rgba({min(255,int(r*1.0+10))},{int(g*0.80)},{min(255,int(b*1.0))},220);
    color: white;
}}
QPushButton:pressed {{
    background: rgba({int(r*0.84)},{int(g*0.48)},{int(b*0.82)},230);
}}
"""


def glass_card_colors() -> tuple[QColor, QColor]:
    """
    Возвращает (top_color, bot_color) для градиента GlassCard.
    Оба цвета — очень тёмный оттенок текущего акцента (насыщенность ~8–15%).
    """
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()
    return (
        QColor(max(10, int(r * 0.085)), max(5,  int(g * 0.047)), max(18, int(b * 0.188))),
        QColor(max(6,  int(r * 0.054)), max(3,  int(g * 0.027)), max(12, int(b * 0.125))),
    )


def scrollbar_ss() -> str:
    """Возвращает QSS тонкого скроллбара в цвете текущей темы."""
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()
    return f"""
QScrollArea, QWidget#sc {{ background: transparent; border: none; }}
QScrollBar:vertical {{ width: 4px; background: transparent; }}
QScrollBar::handle:vertical {{
    background: rgba({int(r*0.91)},{int(g*0.60)},{int(b*0.85)},110);
    border-radius: 2px; min-height: 22px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""