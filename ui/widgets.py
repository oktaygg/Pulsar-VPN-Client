# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/widgets.py — переиспользуемые атомарные виджеты.

Содержит:
  - enable_blur_behind()  — Windows Acrylic-эффект через SetWindowCompositionAttribute.
  - GlassCard             — стеклянная карточка с градиентным фоном и рамкой.
  - ToggleSwitch          — анимированный переключатель.
  - _UsageBar             — полоска использования трафика (private, для VpnSubscriptionCard).
  - _StatusBadge          — бейдж «АКТИВНА / НЕАКТИВНА» (private, для VpnSubscriptionCard).
  - PowerButton           — большая кнопка питания с пульсирующим свечением.
  - CountryGroupLabel     — заголовок группы стран в списке серверов.
  - ServerCard            — строка одного сервера: флаг + имя + пинг.
  - VpnSubscriptionCard   — полная карточка подписки со списком серверов.

Вспомогательные функции (флаги):
  - _flag_emoji_to_cc()   — эмодзи/строка → двухбуквенный код страны.
  - _get_flag_pixmap()    — QPixmap флага из assets/countries/ (с кешем).
  - _make_flag_label()    — QLabel с флагом и закруглёнными углами.

Вспомогательные функции (иконки приложений):
  - _tint_pixmap()        — быстрая перекраска QPixmap в цвет темы.
  - _app_icon_label()     — QLabel с иконкой или буквой-заглушкой.
  - _name_color_ss()      — QSS цвет названия приложения из текущей темы.

Зависимости: ui.theme (ThemeManager, цветовые константы и функции стилей).
"""

import ctypes
import os
import sys
import threading

from PyQt6.QtCore import (
    Qt, QRectF, QSize, QTimer, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon,
    QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ui.theme import (
    ITEM_HOVER, ITEM_SEL_L, ITEM_SEL_R, PANEL_BORDER,
    ThemeManager,
    glass_card_colors, scrollbar_ss, themed_btn_ss,
)

# Путь к корню проекта (родитель папки ui/)
_UI_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_UI_DIR)
_ASSETS_DIR  = os.path.join(_PROJECT_DIR, "assets")


# ══════════════════════════════════════════════════════════
#  WINDOWS ACRYLIC — размытие за окном
# ══════════════════════════════════════════════════════════

def enable_blur_behind(hwnd: int) -> None:
    """
    Включает Windows Acrylic-эффект (размытие фона) для окна по его HWND.
    Работает только на Windows 10/11 через недокументированный
    SetWindowCompositionAttribute. При ошибке — молча игнорирует.
    """
    try:
        class _AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState",   ctypes.c_uint),
                ("AccentFlags",   ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId",   ctypes.c_uint),
            ]

        class _WinCompAttrData(ctypes.Structure):
            _fields_ = [
                ("Attribute",   ctypes.c_int),
                ("pData",       ctypes.c_void_p),
                ("ulDataSize",  ctypes.c_ulong),
            ]

        accent = _AccentPolicy()
        accent.AccentState   = 4           # ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags   = 2
        accent.GradientColor = 0xCC0A0518  # AABBGGRR: полупрозрачный тёмно-фиолетовый

        data = _WinCompAttrData()
        data.Attribute  = 19              # WCA_ACCENT_POLICY
        data.pData      = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.ulDataSize = ctypes.sizeof(accent)

        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.pointer(data))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════
#  GLASS CARD — стеклянная карточка
# ══════════════════════════════════════════════════════════

class GlassCard(QWidget):
    """
    Контейнер-карточка с тёмным градиентным фоном и тонкой цветной рамкой.
    Градиент и цвет рамки автоматически обновляются при смене темы.

    Args:
        radius: Радиус скругления углов в пикселях.
        alpha:  Прозрачность фона (0 = прозрачный, 255 = непрозрачный).
    """

    def __init__(self, radius: int = 14, alpha: int = 185, parent=None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._alpha  = alpha
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Чуть уменьшаем rect чтобы рамка не обрезалась по краю
        rf   = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rf, self._radius, self._radius)

        # Градиентный фон: сверху чуть светлее, снизу темнее
        top_c, bot_c = glass_card_colors()
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor(top_c.red(), top_c.green(), top_c.blue(), self._alpha))
        grad.setColorAt(1, QColor(bot_c.red(), bot_c.green(), bot_c.blue(), self._alpha))

        p.setClipPath(path)
        p.fillPath(path, QBrush(grad))
        p.setClipping(False)

        # Рамка в цвете темы
        p.setPen(QPen(PANEL_BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


# ══════════════════════════════════════════════════════════
#  TOGGLE SWITCH — анимированный переключатель
# ══════════════════════════════════════════════════════════

class ToggleSwitch(QWidget):
    """
    Переключатель ON/OFF с плавной анимацией кружка.
    Анимация реализована через QTimer без pyqtProperty — работает
    даже когда виджет не показан на экране.

    Сигнал toggled(bool) испускается сразу при клике, не дожидаясь
    окончания анимации.
    """

    toggled = pyqtSignal(bool)

    _DURATION_MS = 180   # длительность анимации переключения, мс
    _FPS         = 60    # частота обновления анимации, кадр/с

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._pos     = 1.0 if checked else 0.0   # текущая позиция: 0.0=выкл, 1.0=вкл
        self._target  = self._pos

        self.setFixedSize(46, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._timer = QTimer(self)
        self._timer.setInterval(1000 // self._FPS)
        self._timer.timeout.connect(self._step)

        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def mousePressEvent(self, _event) -> None:
        self._checked = not self._checked
        self._target  = 1.0 if self._checked else 0.0
        self._timer.start()
        self.toggled.emit(self._checked)

    def _step(self) -> None:
        """Один шаг линейной интерполяции позиции кружка."""
        step = 1.0 / (self._DURATION_MS / 1000 * self._FPS)
        if self._pos < self._target:
            self._pos = min(self._pos + step, self._target)
        else:
            self._pos = max(self._pos - step, self._target)
        self.update()
        if abs(self._pos - self._target) < 0.001:
            self._pos = self._target
            self._timer.stop()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        t    = self._pos
        ac   = ThemeManager.instance().color()

        # Цвет дорожки: интерполяция между «выкл» (тёмный) и «вкл» (акцент)
        off_r = int(ac.red()   * 0.18 + 20)
        off_g = int(ac.green() * 0.18 + 18)
        off_b = int(ac.blue()  * 0.18 + 35)
        track_color = QColor(
            int(ac.red()   * t + off_r * (1 - t)),
            int(ac.green() * t + off_g * (1 - t)),
            int(ac.blue()  * t + off_b * (1 - t)),
            210,
        )
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 13, 13)

        # Кружок: скользит от левого к правому краю
        margin = 3
        knob_x = margin + t * (rect.width() - 2 * margin - (rect.height() - 2 * margin))
        p.setBrush(QBrush(QColor(240, 235, 255)))
        p.drawEllipse(
            int(knob_x), margin,
            rect.height() - 2 * margin,
            rect.height() - 2 * margin,
        )


# ══════════════════════════════════════════════════════════
#  ФЛАГИ СТРАН
# ══════════════════════════════════════════════════════════

_FLAG_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _flag_emoji_to_cc(s: str) -> str:
    """
    Приводит любой ввод к двухбуквенному коду страны в нижнем регистре.

    Принимает:
      - Эмодзи флага:  «🇷🇺» → «ru»
      - Код страны:    «RU» или «ru» → «ru»
      - Пустую строку → «»
    """
    if not s:
        return ""
    s = s.strip()
    # Региональные индикаторы Unicode: U+1F1E6 (A) … U+1F1FF (Z)
    if len(s) >= 2:
        codepoints = [ord(c) for c in s]
        if all(0x1F1E6 <= cp <= 0x1F1FF for cp in codepoints[:2]):
            return (
                chr(codepoints[0] - 0x1F1E6 + ord("a"))
                + chr(codepoints[1] - 0x1F1E6 + ord("a"))
            )
    return s.lower()[:2]


def _get_flag_pixmap(cc: str, size: int = 22) -> QPixmap:
    """
    Возвращает QPixmap флага страны из assets/countries/<cc>.png.
    Если файл не найден — возвращает заглушку gg.png.
    Результаты кешируются по ключу «<cc>_<size>».
    """
    cc_key    = _flag_emoji_to_cc(cc or "")
    cache_key = f"{cc_key}_{size}"
    if cache_key in _FLAG_PIXMAP_CACHE:
        return _FLAG_PIXMAP_CACHE[cache_key]

    # Ищем папку assets/countries: рядом с ui/, рядом с точкой входа, в cwd
    candidates = [
        _PROJECT_DIR,
        os.path.dirname(os.path.abspath(sys.argv[0])),
        os.getcwd(),
    ]
    base = next(
        (os.path.join(c, "assets", "countries")
         for c in candidates
         if os.path.isdir(os.path.join(c, "assets", "countries"))),
        os.path.join(_PROJECT_DIR, "assets", "countries"),
    )

    def _load(name: str) -> QPixmap | None:
        path = os.path.join(base, name)
        if os.path.isfile(path):
            px = QPixmap(path)
            if not px.isNull():
                return px.scaled(
                    int(size * 1.5), size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        return None

    px = _load(f"{cc_key}.png")
    if px is None:
        print(f"[FLAG] not found: {cc_key}.png → fallback gg.png")
        px = _load("gg.png") or QPixmap()

    _FLAG_PIXMAP_CACHE[cache_key] = px
    return px


def _make_flag_label(cc: str, size: int = 22, parent=None) -> QLabel:
    """
    Создаёт QLabel с флагом страны и закруглёнными углами (radius=3).
    Если изображение не найдено — возвращает пустой QLabel нужного размера.
    """
    px_src = _get_flag_pixmap(cc, size)

    if not px_src.isNull():
        w, h    = px_src.width(), px_src.height()
        rounded = QPixmap(w, h)
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 3, 3)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, px_src)
        painter.end()
        px_final = rounded
    else:
        px_final = px_src

    lbl = QLabel(parent)
    lbl.setFixedSize(int(size * 1.5) + 4, size + 4)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("background: transparent;")
    if not px_final.isNull():
        lbl.setPixmap(px_final)
    return lbl


# ══════════════════════════════════════════════════════════
#  ИКОНКИ ПРИЛОЖЕНИЙ
# ══════════════════════════════════════════════════════════

def _tint_pixmap(src: QPixmap, color: QColor) -> QPixmap:
    """
    Перекрашивает QPixmap в заданный цвет через CompositionMode_SourceIn.
    Форма (прозрачность) сохраняется, цвет меняется полностью.
    Возвращает новый QPixmap — исходник не изменяется.
    """
    result = QPixmap(src.size())
    result.fill(Qt.GlobalColor.transparent)
    p = QPainter(result)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(result.rect(), color)
    p.end()
    return result


def _theme_icon_color() -> QColor:
    """Возвращает цвет иконок в текущей теме (светлый оттенок акцента)."""
    c = ThemeManager.instance().color()
    return QColor(
        min(255, int(c.red()   * 0.83 + 40)),
        min(255, int(c.green() * 0.68 + 50)),
        min(255, int(c.blue()  * 0.80 + 40)),
    )


def _app_icon_label(name: str, size: int = 36) -> QLabel:
    """
    Создаёт QLabel с иконкой приложения из assets/wl_images/<name>.png.
    Если файл не найден — показывает первую букву имени на цветном фоне.
    """
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

    icon_path = os.path.join(_ASSETS_DIR, "wl_images", f"{name}.png")
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()

    if os.path.isfile(icon_path):
        px = QPixmap(icon_path).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        lbl.setPixmap(px)
        lbl.setStyleSheet("border-radius: 8px;")
    else:
        lbl.setText(name[0].upper())
        lbl.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        lbl.setStyleSheet(
            f"border-radius: 8px;"
            f"background: rgba({int(r*0.45)},{int(g*0.25)},{int(b*0.50)},110);"
            f"color: rgba({min(255,int(r*0.80+60))},{min(255,int(g*0.70+60))},"
            f"{min(255,int(b*0.60+80))},220);"
        )
    return lbl


def _name_color_ss() -> str:
    """Возвращает QSS цвета текста для названия приложения в белом списке."""
    c = ThemeManager.instance().color()
    r, g, b = c.red(), c.green(), c.blue()
    return (
        f"color: rgba({min(255,int(r*0.80+80))},{min(255,int(g*0.72+80))},"
        f"{min(255,int(b*0.60+100))},230); background: transparent;"
    )


# ══════════════════════════════════════════════════════════
#  USAGE BAR — полоска использования трафика
# ══════════════════════════════════════════════════════════

class _UsageBar(QWidget):
    """
    Горизонтальная полоска использования трафика.
    Слева — заполнение пропорционально used/limit,
    справа — текстовая метка «X.X ГБ / Y ГБ».
    При limit=None показывает «∞» и полоску заполнена на 55%.
    """

    def __init__(self, used_gb: float, limit_gb: float | None, parent=None) -> None:
        super().__init__(parent)
        self._used  = used_gb
        self._limit = limit_gb
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(22)
        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        ac   = ThemeManager.instance().color()
        r, g, b = ac.red(), ac.green(), ac.blue()
        w, h = self.width(), self.height()

        # Текстовая метка справа
        limit_str = "∞" if self._limit is None else f"{self._limit:.0f} ГБ"
        label = f"{self._used:.1f} ГБ / {limit_str}"
        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QPen(QColor(155, 170, 210, 140)))
        fm = p.fontMetrics()
        label_w = fm.horizontalAdvance(label)
        p.drawText(w - label_w, h - 4, label)

        # Трек (фон полоски)
        bar_right = w - label_w - 8
        bar_h, bar_y = 5, (h - 5) // 2
        p.setBrush(QBrush(QColor(255, 255, 255, 18)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, bar_y, bar_right, bar_h), 2.5, 2.5)

        # Заполнение
        ratio  = (self._used / self._limit) if self._limit else 0.55
        ratio  = min(ratio, 1.0)
        fill_w = bar_right * ratio
        if fill_w > 0:
            grad = QLinearGradient(0, 0, fill_w, 0)
            grad.setColorAt(0.0, QColor(
                int(r * 0.65 + 30), int(g * 0.55 + 30), int(b * 0.65 + 30), 210))
            grad.setColorAt(1.0, QColor(
                min(255, int(r * 0.80 + 60)), min(255, int(g * 0.72 + 60)),
                min(255, int(b * 0.80 + 40)), 240))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(QRectF(0, bar_y, fill_w, bar_h), 2.5, 2.5)


# ══════════════════════════════════════════════════════════
#  STATUS BADGE — бейдж «АКТИВНА / НЕАКТИВНА»
# ══════════════════════════════════════════════════════════

class _StatusBadge(QWidget):
    """Маленький цветной бейдж статуса подписки."""

    def __init__(self, active: bool, parent=None) -> None:
        super().__init__(parent)
        self._active = active
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(24)
        # Ширина подгоняется под текст
        text = "АКТИВНА" if active else "НЕАКТИВНА"
        fm = QFontMetrics(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.setFixedWidth(fm.horizontalAdvance(text) + 22)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._active:
            bg     = QColor( 39, 174,  96,  45)
            border = QColor( 39, 174,  96, 100)
            text_c = QColor( 70, 220, 130, 230)
        else:
            bg     = QColor(180,  60,  60,  45)
            border = QColor(180,  60,  60, 100)
            text_c = QColor(220,  80,  80, 230)

        rf = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setBrush(QBrush(bg))
        p.setPen(QPen(border, 1))
        p.drawRoundedRect(rf, 5, 5)

        text = "АКТИВНА" if self._active else "НЕАКТИВНА"
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QPen(text_c))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)


# ══════════════════════════════════════════════════════════
#  POWER BUTTON — кнопка питания с пульсацией
# ══════════════════════════════════════════════════════════

class PowerButton(QWidget):
    """
    Круглая кнопка питания 260×260 px с пульсирующим радиальным свечением.
    В состоянии «отключено» — серая, в состоянии «подключено» — цвет темы.
    """

    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._connected = False
        self._hovered   = False
        self._glow      = 40       # текущая интенсивность свечения
        self._glow_dir  = 1        # направление пульсации: +1 или -1

        self.setFixedSize(260, 260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        pulse_timer = QTimer(self)
        pulse_timer.timeout.connect(self._pulse)
        pulse_timer.start(30)

        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def set_connected(self, connected: bool) -> None:
        """Переключает визуальное состояние кнопки."""
        self._connected = connected

    def _pulse(self) -> None:
        """Один шаг пульсации свечения."""
        self._glow += self._glow_dir * 2
        if self._glow >= 120:
            self._glow_dir = -1
        if self._glow <= 40:
            self._glow_dir = 1
        self.update()

    def enterEvent(self, _event) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hovered = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _event) -> None:
        p  = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        R  = 84
        ac = ThemeManager.instance().color()

        # Цвет кнопки: акцент при подключении, серый при отключении
        if self._connected:
            gc = ac
        else:
            grey = 155 if self._hovered else 130
            gc   = QColor(grey, grey, grey + 12)

        # Радиальное свечение
        glow_r = 130
        rg = QRadialGradient(float(cx), float(cy), float(glow_r))
        rg.setColorAt(0.0, QColor(gc.red(), gc.green(), gc.blue(), int(self._glow * 1.5)))
        rg.setColorAt(0.2, QColor(gc.red(), gc.green(), gc.blue(), self._glow))
        rg.setColorAt(0.4, QColor(gc.red(), gc.green(), gc.blue(), int(self._glow * 0.5)))
        rg.setColorAt(0.6, QColor(gc.red(), gc.green(), gc.blue(), int(self._glow * 0.2)))
        rg.setColorAt(0.8, QColor(gc.red(), gc.green(), gc.blue(), int(self._glow * 0.05)))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(rg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, self.width(), self.height())

        # Тело круга (полупрозрачный фон)
        bg = QRadialGradient(float(cx), float(cy - 12), float(R))
        if self._connected:
            bg.setColorAt(0, QColor(
                int(ac.red() * 0.22), int(ac.green() * 0.12), int(ac.blue() * 0.25), 32))
            bg.setColorAt(1, QColor(
                int(ac.red() * 0.08), int(ac.green() * 0.04), int(ac.blue() * 0.10), 16))
        else:
            bg.setColorAt(0, QColor(62, 62, 72, 38))
            bg.setColorAt(1, QColor(28, 28, 34, 20))
        p.setBrush(QBrush(bg))

        border_alpha = 240 if self._hovered else 185
        border_width = 3.5 if self._hovered else 2.5
        p.setPen(QPen(QColor(gc.red(), gc.green(), gc.blue(), border_alpha), border_width))
        p.drawEllipse(cx - R, cy - R, R * 2, R * 2)

        # Иконка питания (дуга + вертикальная линия)
        if self._connected:
            ic = ac
        else:
            grey_ic = 185 if self._hovered else 158
            ic = QColor(grey_ic, grey_ic, grey_ic + 14)

        pen = QPen(ic, 5.0, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(cx - 32, cy - 32, 64, 64, 150 * 16, 240 * 16)
        p.drawLine(cx, cy - 32, cx, cy)


# ══════════════════════════════════════════════════════════
#  COUNTRY GROUP LABEL — заголовок группы стран
# ══════════════════════════════════════════════════════════

class CountryGroupLabel(QWidget):
    """Заголовок группы серверов одной страны: флаг + название."""

    def __init__(self, flag: str, country: str, cc: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(31)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(7)

        lay.addWidget(_make_flag_label(cc or flag, size=18))

        self._name_lbl = QLabel(country)
        self._name_lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lay.addWidget(self._name_lbl)
        lay.addStretch()

        self._retheme(ThemeManager.instance().color())
        ThemeManager.instance().connect_theme(self, self._retheme)

    def _retheme(self, c: QColor) -> None:
        r, g, b = c.red(), c.green(), c.blue()
        self._name_lbl.setStyleSheet(
            f"color: rgba({int(r*0.65+30)},{int(g*0.50+50)},{int(b*0.65+30)},185);"
            f" background: transparent; letter-spacing: 1px;"
        )


# ══════════════════════════════════════════════════════════
#  SERVER CARD — строка одного VPN-сервера
# ══════════════════════════════════════════════════════════

class ServerCard(QWidget):
    """
    Строка сервера: флаг страны + название + пинг.
    Поддерживает состояния hover и selected с визуальной подсветкой.
    """

    clicked = pyqtSignal(dict)

    def __init__(self, data: dict, parent=None) -> None:
        super().__init__(parent)
        self.data  = data
        self._sel  = False
        self._hov  = False

        self.setFixedHeight(41)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 10, 0)
        lay.setSpacing(10)

        # Флаг
        lay.addWidget(_make_flag_label(data.get("cc", ""), size=22))

        # Название (с обрезкой по ширине)
        self._name_lbl = QLabel()
        self._name_lbl.setFont(QFont("Segoe UI", 13))
        self._name_lbl.setStyleSheet("color: rgba(210,218,250,220); background: transparent;")

        raw_name = data.get("name", "").lstrip()
        # Убираем эмодзи-флаги из начала строки (региональные индикаторы > U+2000)
        while raw_name and ord(raw_name[0]) > 0x2000:
            raw_name = raw_name[1:].lstrip()

        fm = QFontMetrics(QFont("Segoe UI", 13))
        # Доступная ширина: панель 408px − отступы(34) − флаг(36) − пинг(70) − spacing
        elided = fm.elidedText(raw_name, Qt.TextElideMode.ElideRight, 210)
        self._name_lbl.setText(elided)
        self._name_lbl.setToolTip(raw_name)
        lay.addWidget(self._name_lbl, 1)

        # Пинг
        self._ping_lbl = QLabel()
        self._ping_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.Medium))
        self._ping_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._ping_lbl.setFixedWidth(70)

        ping = data.get("ping")
        if ping is None:
            self._ping_lbl.setText("—")
            self._ping_lbl.setStyleSheet(
                "color: rgba(120,130,165,80); background: transparent;")
        else:
            if ping < 80:
                col = "rgba(70,220,130,230)"
            elif ping < 150:
                col = "rgba(240,192,64,230)"
            else:
                col = "rgba(240,112,64,230)"
            self._ping_lbl.setText(f"{ping} ms")
            self._ping_lbl.setStyleSheet(f"color: {col}; background: transparent;")
        lay.addWidget(self._ping_lbl)

        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def setSelected(self, selected: bool) -> None:
        self._sel = selected
        self.update()

    def enterEvent(self, _event) -> None:
        self._hov = True
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hov = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.data)

    def paintEvent(self, _event) -> None:
        p  = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ac = ThemeManager.instance().color()
        rf = QRectF(2, 1, self.width() - 4, self.height() - 2)

        if self._sel:
            g = QLinearGradient(0, 0, self.width(), 0)
            g.setColorAt(0, ITEM_SEL_L)
            g.setColorAt(1, ITEM_SEL_R)
            p.setBrush(QBrush(g))
            p.setPen(QPen(QColor(ac.red(), ac.green(), ac.blue(), 120), 1))
            p.drawRoundedRect(rf, 8, 8)
        elif self._hov:
            p.setBrush(QBrush(ITEM_HOVER))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(rf, 8, 8)


# ══════════════════════════════════════════════════════════
#  VPN SUBSCRIPTION CARD — карточка подписки
# ══════════════════════════════════════════════════════════

class VpnSubscriptionCard(QWidget):
    """
    Полная карточка VPN-подписки: заголовок + трафик + статус + список серверов.

    Сигналы:
      server_selected(dict)  — пользователь выбрал сервер.
      refresh_requested()    — нажата кнопка «Обновить».
      delete_requested()     — нажата кнопка «Удалить».
    """

    server_selected   = pyqtSignal(dict)
    refresh_requested = pyqtSignal()
    delete_requested  = pyqtSignal()

    def __init__(self, sub: dict, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sub          = sub
        self._server_cards: list[ServerCard] = []
        self._sel_card:     ServerCard | None = None
        self._themed_btns:  list[QPushButton] = []
        self._vpn_active   = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._glass = GlassCard(radius=14, alpha=185)
        self._glass.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._glass)

        inner = QVBoxLayout(self._glass)
        inner.setContentsMargins(17, 12, 17, 12)
        inner.setSpacing(7)

        # ── Заголовок ───────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(7)
        name_lbl = QLabel(sub["name"])
        name_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        name_lbl.setStyleSheet(
            "color: rgba(232,226,255,245); background: transparent; letter-spacing: 1px;")
        hdr.addWidget(name_lbl)
        hdr.addStretch()

        self._refresh_btn = None
        self._copy_btn    = None
        self._delete_btn  = None

        # Кнопки в заголовке
        for png_rel, fallback, tip in [
            ("assets/app_images/reload.png", "↻", "Обновить серверы"),
            ("assets/app_images/copy.png",   "⎘", "Копировать ссылку"),
            ("",                             "✕", "Удалить подписку"),
        ]:
            if not png_rel:
                # Текстовая кнопка (удалить)
                btn = QPushButton("✕")
                btn.setFixedSize(34, 34)
                btn.setFont(QFont("Segoe UI", 17))
                btn.setToolTip(tip)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(themed_btn_ss("padding-bottom: 1px; padding-left: 1px;"))
            else:
                btn = self._make_icon_btn(png_rel, fallback, tip)

            self._themed_btns.append(btn)
            hdr.addWidget(btn)

            if fallback == "↻":
                self._refresh_btn = btn
                btn.clicked.connect(self._on_refresh_clicked)
            elif fallback == "⎘":
                self._copy_btn = btn
                btn.clicked.connect(self._on_copy_clicked)
            elif fallback == "✕":
                self._delete_btn = btn
                btn.clicked.connect(self._on_delete_clicked)

        inner.addLayout(hdr)

        # ── Полоска трафика ──────────────────────────────────
        inner.addWidget(_UsageBar(sub["usage_gb"], sub["limit_gb"]))

        # ── Статус: бейдж + срок + дни ──────────────────────
        st_row = QHBoxLayout()
        st_row.setSpacing(8)
        st_row.addWidget(_StatusBadge(sub["active"]))

        for text, style in [
            ("|",                    "color: rgba(120,130,165,100); background: transparent;"),
            (f"до {sub['expires']}", "color: rgba(160,175,210,170); background: transparent;"),
            ("|",                    "color: rgba(120,130,165,100); background: transparent;"),
            (f"{sub['days_left']} дн", "color: rgba(130,145,185,140); background: transparent;"),
        ]:
            lbl = QLabel(text)
            lbl.setFont(QFont("Segoe UI", 12))
            lbl.setStyleSheet(style)
            st_row.addWidget(lbl)

        st_row.addStretch()
        inner.addLayout(st_row)

        # ── Разделитель ──────────────────────────────────────
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(
            "color: rgba(45,100,200,40); background: rgba(45,100,200,40);")
        div.setFixedHeight(1)
        inner.addWidget(div)

        # ── Список серверов (скролл) ─────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(scrollbar_ss())
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        cw = QWidget()
        cw.setObjectName("sc")
        cw.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 2, 0, 2)
        cl.setSpacing(0)

        for srv in sub["servers"]:
            card = ServerCard(srv)
            card.clicked.connect(self._on_server_click_guarded)
            cl.addWidget(card)
            self._server_cards.append(card)

        cl.addStretch()
        self._scroll.setWidget(cw)
        inner.addWidget(self._scroll)

        # Выбираем первый сервер по умолчанию
        if self._server_cards:
            self._select(self._server_cards[0])

        ThemeManager.instance().connect_theme(self, self._retheme)

    # ── Вспомогательный метод: кнопка с PNG-иконкой ──────

    def _make_icon_btn(self, png_rel: str, fallback: str, tip: str) -> QPushButton:
        """Создаёт кнопку 34×34 с PNG-иконкой в цвете темы."""
        btn = QPushButton()
        btn.setFixedSize(34, 34)
        btn.setToolTip(tip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(themed_btn_ss())

        icon_path = os.path.join(_PROJECT_DIR, png_rel)
        btn.setProperty("icon_png_path", icon_path)
        src = QPixmap(icon_path)

        if not src.isNull():
            colored = _tint_pixmap(src, _theme_icon_color())
            scaled  = colored.scaled(
                20, 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            btn.setIcon(QIcon(scaled))
            btn.setIconSize(QSize(20, 20))
        else:
            btn.setText(fallback)
            btn.setFont(QFont("Segoe UI", 16))

        return btn

    # ── Публичный API ─────────────────────────────────────

    def set_refreshing(self, loading: bool) -> None:
        """Блокирует/разблокирует кнопку обновления во время загрузки."""
        if self._refresh_btn:
            self._refresh_btn.setEnabled(not loading)
            self._refresh_btn.setText("⏳" if loading else "")
            if not loading:
                # Восстанавливаем иконку
                icon_path = self._refresh_btn.property("icon_png_path")
                if icon_path:
                    src = QPixmap(icon_path)
                    if not src.isNull():
                        colored = _tint_pixmap(src, _theme_icon_color())
                        scaled  = colored.scaled(
                            20, 20,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self._refresh_btn.setIcon(QIcon(scaled))
                        self._refresh_btn.setIconSize(QSize(20, 20))

    def set_vpn_active(self, active: bool) -> None:
        """Сохраняет флаг активного VPN — блокирует изменение подписки."""
        self._vpn_active = active

    def selected_server(self) -> dict | None:
        """Возвращает данные выбранного сервера или None."""
        return self._sel_card.data if self._sel_card else None

    # ── Обработчики ──────────────────────────────────────

    def _retheme(self, _c: QColor) -> None:
        """Перекрашивает кнопки и скроллбар при смене темы."""
        self._scroll.setStyleSheet(scrollbar_ss())
        icon_color = _theme_icon_color()
        for btn in self._themed_btns:
            btn.setStyleSheet(themed_btn_ss())
            icon_path = btn.property("icon_png_path")
            if icon_path:
                src = QPixmap(icon_path)
                if not src.isNull():
                    colored = _tint_pixmap(src, icon_color)
                    scaled  = colored.scaled(
                        20, 20,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    btn.setIcon(QIcon(scaled))
                    btn.setIconSize(QSize(20, 20))

    def _on_server_click(self, data: dict) -> None:
        for card in self._server_cards:
            if card.data is data:
                self._select(card)
                break

    def _select(self, card: ServerCard) -> None:
        if self._sel_card:
            self._sel_card.setSelected(False)
        self._sel_card = card
        card.setSelected(True)
        self.server_selected.emit(card.data)

    def _vpn_warn(self) -> None:
        """Проигрывает системный звук при попытке действия во время VPN."""
        def _beep():
            try:
                import winsound
                winsound.PlaySound(
                    "SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        threading.Thread(target=_beep, daemon=True).start()

        # Импортируем здесь, чтобы избежать циклического импорта с servers_page
        from ui.servers_page import VpnWarnOverlay
        dlg = VpnWarnOverlay(parent=self.window())
        dlg.show()

    def _on_refresh_clicked(self) -> None:
        if self._vpn_active:
            self._vpn_warn()
            return
        self.refresh_requested.emit()

    def _on_copy_clicked(self) -> None:
        url = self._sub.get("subscription_url", "").strip()
        if not url:
            return
        QApplication.clipboard().setText(url)

        # Коротко показываем ✓ вместо иконки
        if self._copy_btn:
            btn = self._copy_btn
            btn.setIcon(QIcon())
            btn.setText("✓")
            btn.setFont(QFont("Segoe UI", 16))

            def _restore():
                btn.setText("")
                icon_path = btn.property("icon_png_path")
                if icon_path:
                    src = QPixmap(icon_path)
                    if not src.isNull():
                        colored = _tint_pixmap(src, _theme_icon_color())
                        scaled  = colored.scaled(
                            20, 20,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        btn.setIcon(QIcon(scaled))
                        btn.setIconSize(QSize(20, 20))

            QTimer.singleShot(1200, _restore)

    def _on_delete_clicked(self) -> None:
        if self._vpn_active:
            self._vpn_warn()
            return
        self.delete_requested.emit()

    def _on_server_click_guarded(self, data: dict) -> None:
        if self._vpn_active:
            self._vpn_warn()
            return
        self._on_server_click(data)