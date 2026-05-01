# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/whitelist_page.py — страница белых списков приложений.

Содержит:
  - _get_running_processes()  — список запущенных .exe через psutil.
  - _extract_process_icon()   — иконка .exe через Win32 API → QPixmap.
  - _HoverRow                 — базовый виджет строки с hover-подсветкой.
  - _Checkbox                 — кастомный чекбокс в цвете темы.
  - _PanelHeader              — заголовок панели с разделителем и опциональной кнопкой «+».
  - ProcessRow                — строка запущенного процесса в оверлее.
  - PopularAppRow             — строка «популярного» приложения (колонка 1): иконка + имя + чекбокс.
  - AddedAppRow               — строка добавленного приложения (колонка 2): иконка + имя + тогл.
  - AddProcessOverlay         — оверлей со списком запущенных процессов и поиском.
  - WhitelistPage             — главная страница с двумя колонками и поиском.

Зависимости:
  ui.theme   — ThemeManager, цветовые константы, функции стилей.
  ui.config  — WhitelistState, AppSettings, load_apps_json, add_app, APP_EXE_MAP.
  ui.widgets — GlassCard, ToggleSwitch, _app_icon_label, _name_color_ss.
"""

import os
import sys

from PyQt6.QtCore import Qt, QRectF, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QIcon,
    QImage, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QGraphicsBlurEffect, QGraphicsOpacityEffect,
    QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

from ui.theme import (
    ITEM_HOVER,
    ThemeManager,
    scrollbar_ss, themed_btn_ss,
)
from ui.config import (
    APP_EXE_MAP, AppSettings, WhitelistState,
    load_apps_json, add_app as _add_app_to_json,
)
from ui.widgets import GlassCard, ToggleSwitch, _app_icon_label, _name_color_ss

# Путь к корню проекта: ui/ → project/
_UI_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_UI_DIR)


# ══════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════

def _get_running_processes() -> list[dict]:
    """
    Возвращает список запущенных процессов (без дублей по exe-имени).
    Каждый элемент: {'name': str, 'exe': str, 'exe_path': str, 'pid': int}.
    name  — красивое имя без расширения (напр. «Telegram»).
    exe   — полное имя файла (напр. «Telegram.exe»).
    """
    if not _PSUTIL_OK:
        return []
    seen_exe: set[str] = set()
    result:   list[dict] = []
    try:
        for proc in psutil.process_iter(["name", "exe", "pid"]):
            try:
                info     = proc.info
                exe_name = info.get("name") or ""
                if not exe_name or exe_name.lower() in ("system", "idle", "registry"):
                    continue
                key = exe_name.lower()
                if key in seen_exe:
                    continue
                seen_exe.add(key)
                result.append({
                    "name":     os.path.splitext(exe_name)[0],
                    "exe":      exe_name,
                    "exe_path": info.get("exe") or "",
                    "pid":      info.get("pid", 0),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except Exception as e:
        print(f"[psutil] {e}")
    result.sort(key=lambda x: x["name"].lower())
    return result


def _extract_process_icon(exe_path: str, name: str, size: int = 36) -> QPixmap | None:
    """
    Извлекает иконку исполняемого файла через Win32 API и возвращает QPixmap.
    Если файл не найден или Win32 недоступен — возвращает None.
    """
    if not exe_path or not os.path.isfile(exe_path):
        return None
    try:
        import win32ui, win32gui, win32con
        from PyQt6.QtGui import QImage

        ico_size = 32
        large, small = win32gui.ExtractIconEx(exe_path, 0)
        if not large and not small:
            return None
        icon_handle = large[0] if large else small[0]

        hdc_screen = win32gui.GetDC(0)
        hdc        = win32ui.CreateDCFromHandle(hdc_screen)
        hdc2       = hdc.CreateCompatibleDC()
        hbmp       = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, ico_size, ico_size)
        hdc2.SelectObject(hbmp)
        hdc2.FillSolidRect((0, 0, ico_size, ico_size), 0x00000000)
        win32gui.DrawIconEx(
            hdc2.GetSafeHdc(), 0, 0, icon_handle,
            ico_size, ico_size, 0, None, win32con.DI_NORMAL,
        )

        bmpstr = hbmp.GetBitmapBits(True)
        img_qt = QImage(bmpstr, ico_size, ico_size, QImage.Format.Format_ARGB32)
        px     = QPixmap.fromImage(img_qt).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        for h in large:
            try: win32gui.DestroyIcon(h)
            except Exception: pass
        for h in small:
            try: win32gui.DestroyIcon(h)
            except Exception: pass
        hdc2.DeleteDC()
        hdc.DeleteDC()
        win32gui.ReleaseDC(0, hdc_screen)

        return px if not px.isNull() else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
#  БАЗОВЫЕ СТРОКИ
# ══════════════════════════════════════════════════════════

class _HoverRow(QWidget):
    """Базовый виджет строки с hover-подсветкой."""

    def __init__(self, height: int = 54, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(height)
        self._hovered = False
        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def enterEvent(self, _e) -> None:
        self._hovered = True
        self.update()

    def leaveEvent(self, _e) -> None:
        self._hovered = False
        self.update()

    def paintEvent(self, _e) -> None:
        if not self._hovered:
            return
        p  = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rf = QRectF(2, 1, self.width() - 4, self.height() - 2)
        p.setBrush(QBrush(ITEM_HOVER))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rf, 9, 9)


class _Checkbox(QWidget):
    """Кастомный чекбокс в цвете текущей темы."""

    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        ThemeManager.instance().connect_theme(self, lambda _c: self.update())

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, v: bool, emit: bool = True) -> None:
        if self._checked == v:
            return
        self._checked = v
        self.update()
        if emit:
            self.toggled.emit(v)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.set_checked(not self._checked)

    def paintEvent(self, _e) -> None:
        p          = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c          = ThemeManager.instance().color()
        r, g, b    = c.red(), c.green(), c.blue()
        rf         = QRectF(2, 2, 28, 28)

        if self._checked:
            p.setBrush(QBrush(QColor(int(r * 0.75), int(g * 0.48), int(b * 0.80), 220)))
            p.setPen(QPen(QColor(int(r * 0.90), int(g * 0.62), int(b * 0.95), 255), 1.8))
            p.drawRoundedRect(rf, 7, 7)
            pen = QPen(
                QColor(240, 235, 255), 2.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(7, 16, 13, 22)
            p.drawLine(13, 22, 25, 9)
        else:
            p.setBrush(QBrush(QColor(int(r * 0.18), int(g * 0.10), int(b * 0.22), 100)))
            p.setPen(QPen(QColor(int(r * 0.55), int(g * 0.35), int(b * 0.60), 130), 1.8))
            p.drawRoundedRect(rf, 7, 7)


class _PanelHeader(QWidget):
    """Заголовок колонки с горизонтальным разделителем снизу и опциональной кнопкой «+»."""

    def __init__(self, text: str, add_btn: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedHeight(46)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(8)

        self._lbl = QLabel(text)
        self._lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        lay.addWidget(self._lbl)
        lay.addStretch()

        self._plus_btn: QPushButton | None = None
        if add_btn:
            btn = QPushButton("+")
            btn.setFixedSize(34, 34)
            btn.setFont(QFont("Segoe UI", 20, QFont.Weight.Normal))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("Добавить приложение")
            lay.addWidget(btn)
            self._plus_btn = btn

        self._retheme(ThemeManager.instance().color())
        ThemeManager.instance().connect_theme(self, self._retheme)

    def plus_btn(self) -> QPushButton | None:
        """Возвращает кнопку «+» или None если она не создавалась."""
        return self._plus_btn

    def _retheme(self, _c: QColor) -> None:
        self._lbl.setStyleSheet(
            "color: rgba(255,255,255,220); background: transparent;")
        if self._plus_btn:
            self._plus_btn.setStyleSheet(
                themed_btn_ss("padding-left: 1px; padding-bottom: 4px;"))

    def paintEvent(self, _e) -> None:
        p       = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        p.setPen(QPen(QColor(int(r * 0.55), int(g * 0.35), int(b * 0.60), 60), 1))
        p.drawLine(12, self.height() - 1, self.width() - 12, self.height() - 1)


# ══════════════════════════════════════════════════════════
#  СТРОКИ ПРИЛОЖЕНИЙ
# ══════════════════════════════════════════════════════════

class PopularAppRow(_HoverRow):
    """
    Строка «популярного» приложения (колонка 1).
    Макет: [иконка] [название] ... [чекбокс]
    Сигнал check_changed(app_name, checked) испускается при смене состояния чекбокса.
    """

    check_changed = pyqtSignal(str, bool)

    def __init__(self, name: str, checked: bool = False, parent=None) -> None:
        super().__init__(54, parent)
        self.app_name = name

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 14, 5)
        lay.setSpacing(10)

        lay.addWidget(_app_icon_label(name))

        self._name_lbl = QLabel(name)
        self._name_lbl.setFont(QFont("Segoe UI", 13))
        self._name_lbl.setStyleSheet(_name_color_ss())
        lay.addWidget(self._name_lbl, 1)

        self._cb = _Checkbox(checked)
        self._cb.toggled.connect(lambda v: self.check_changed.emit(self.app_name, v))
        lay.addWidget(self._cb)

        ThemeManager.instance().connect_theme(self, self._retheme)

    def _retheme(self, _c: QColor) -> None:
        self._name_lbl.setStyleSheet(_name_color_ss())

    def set_checked(self, v: bool, emit: bool = True) -> None:
        self._cb.set_checked(v, emit)

    def is_checked(self) -> bool:
        return self._cb.is_checked()


class AddedAppRow(_HoverRow):
    """
    Строка добавленного приложения (колонка 2).
    Макет: [иконка] [название] ... [ToggleSwitch]
    """

    def __init__(self, name: str, enabled: bool = False, parent=None) -> None:
        super().__init__(54, parent)
        self.app_name = name

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(10)

        lay.addWidget(_app_icon_label(name))

        self._name_lbl = QLabel(name)
        self._name_lbl.setFont(QFont("Segoe UI", 13))
        self._name_lbl.setStyleSheet(_name_color_ss())
        lay.addWidget(self._name_lbl, 1)

        self._toggle = ToggleSwitch(checked=enabled)
        lay.addWidget(self._toggle)

        ThemeManager.instance().connect_theme(self, self._retheme)

    def _retheme(self, _c: QColor) -> None:
        self._name_lbl.setStyleSheet(_name_color_ss())

    def is_enabled(self) -> bool:
        return self._toggle._checked

    def set_enabled(self, v: bool) -> None:
        """Устанавливает состояние тогла без анимации и без сигнала."""
        self._toggle._checked = v
        self._toggle._pos     = 1.0 if v else 0.0
        self._toggle._target  = self._toggle._pos
        self._toggle.update()


# ══════════════════════════════════════════════════════════
#  ОВЕРЛЕЙ — ДОБАВЛЕНИЕ ПРОЦЕССА
# ══════════════════════════════════════════════════════════

class ProcessRow(_HoverRow):
    """Строка одного запущенного процесса в оверлее: иконка + имя + exe-имя."""

    clicked = pyqtSignal(dict)

    def __init__(self, info: dict, parent=None) -> None:
        super().__init__(48, parent)
        self.info = info
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 14, 4)
        lay.setSpacing(10)

        # Иконка
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        px      = _extract_process_icon(info.get("exe_path", ""), info["name"], 32)
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()

        if px:
            info["_icon_pixmap"] = px
            icon_lbl.setPixmap(px)
            icon_lbl.setStyleSheet("border-radius: 6px;")
        else:
            icon_lbl.setText(info["name"][0].upper())
            icon_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
            icon_lbl.setStyleSheet(
                f"border-radius: 6px;"
                f"background: rgba({int(r*0.45)},{int(g*0.25)},{int(b*0.50)},110);"
                f"color: rgba({min(255,int(r*0.80+60))},{min(255,int(g*0.70+60))},"
                f"{min(255,int(b*0.60+80))},220);"
            )
        lay.addWidget(icon_lbl)

        # Название
        name_lbl = QLabel(info["name"])
        name_lbl.setFont(QFont("Segoe UI", 12))
        name_lbl.setStyleSheet(_name_color_ss())
        lay.addWidget(name_lbl, 1)

        # .exe-имя (мелкое)
        exe_lbl = QLabel(info["exe"])
        exe_lbl.setFont(QFont("Segoe UI", 9))
        exe_lbl.setStyleSheet(
            f"color: rgba({min(255,int(r*0.60+60))},{min(255,int(g*0.50+60))},"
            f"{min(255,int(b*0.45+80))},130); background: transparent;"
        )
        lay.addWidget(exe_lbl)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.info)


class AddProcessOverlay(QWidget):
    """
    Оверлей поверх WhitelistPage — список запущенных процессов с поиском.
    Появляется с fade-in, закрывается кликом вне карточки или кнопкой «Вернуться».

    Сигналы:
      process_selected(name, exe, QPixmap|None) — пользователь выбрал процесс.
      closed()                                  — оверлей закрыт.
    """

    process_selected = pyqtSignal(str, str, object)
    closed           = pyqtSignal()

    def __init__(self, existing_names: set[str], parent=None) -> None:
        super().__init__(parent)
        self._existing = existing_names
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Fade-in эффект
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
        self._card.setFixedSize(440, 530)
        outer.addWidget(self._card, 0, Qt.AlignmentFlag.AlignCenter)

        cl = QVBoxLayout(self._card)
        cl.setContentsMargins(20, 20, 20, 16)
        cl.setSpacing(10)

        # Заголовок
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        title   = QLabel("Запущенные процессы")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color: rgba({min(255,int(r*0.80+60))},{min(255,int(g*0.70+60))},"
            f"{min(255,int(b*0.60+80))},230); background: transparent;"
        )
        cl.addWidget(title)

        # Поиск
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Поиск процесса…")
        self._search.setFont(QFont("Segoe UI", 12))
        self._search.setFixedHeight(36)
        self._search.textChanged.connect(self._filter)
        self._restyle_search()
        cl.addWidget(self._search)

        # Метка ошибки
        self._err_lbl = QLabel("")
        self._err_lbl.setFont(QFont("Segoe UI", 10))
        self._err_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._err_lbl.setStyleSheet(
            "color: rgba(255,110,110,230); background: rgba(120,20,20,70);"
            "border-radius: 6px; padding: 4px 10px;"
        )
        self._err_lbl.setVisible(False)
        cl.addWidget(self._err_lbl)

        # Список процессов
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(scrollbar_ss())
        cw = QWidget()
        cw.setObjectName("sc")
        cw.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(cw)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(2)
        self._proc_rows: list[ProcessRow] = []
        self._load_processes()
        self._list_layout.addStretch()
        scroll.setWidget(cw)
        cl.addWidget(scroll, 1)

        # Кнопка «Вернуться»
        back_btn = QPushButton("← Вернуться")
        back_btn.setFixedHeight(36)
        back_btn.setFont(QFont("Segoe UI", 11))
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.setStyleSheet(themed_btn_ss())
        back_btn.clicked.connect(self._on_close)
        cl.addWidget(back_btn)

        ThemeManager.instance().connect_theme(self, self._on_theme_changed)

    # ── Fade-in ──────────────────────────────────────────

    def _do_fade(self) -> None:
        self._fade_val = min(1.0, self._fade_val + 0.09)
        self._opacity_eff.setOpacity(self._fade_val)
        if self._fade_val >= 1.0:
            self._fade_timer.stop()
            # Снимаем effect — он мешает дочерним виджетам
            self.setGraphicsEffect(None)

    # ── Процессы ─────────────────────────────────────────

    def _load_processes(self) -> None:
        procs = _get_running_processes()
        if not procs:
            c       = ThemeManager.instance().color()
            r, g, b = c.red(), c.green(), c.blue()
            lbl = QLabel("psutil не установлен.\nУстановите: pip install psutil")
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: rgba({min(255,int(r*0.60+80))},{min(255,int(g*0.55+80))},"
                f"{min(255,int(b*0.50+100))},150); background: transparent;"
            )
            self._list_layout.addWidget(lbl)
            return
        for info in procs:
            row = ProcessRow(info)
            row.clicked.connect(self._on_proc_clicked)
            self._list_layout.addWidget(row)
            self._proc_rows.append(row)

    # ── Поиск ────────────────────────────────────────────

    def _filter(self, text: str) -> None:
        self._err_lbl.setVisible(False)
        q = text.strip().lower()
        for row in self._proc_rows:
            match = not q or q in row.info["name"].lower() or q in row.info["exe"].lower()
            row.setVisible(match)

    # ── Клик по процессу ─────────────────────────────────

    def _on_proc_clicked(self, info: dict) -> None:
        name = info["name"]
        exe  = info["exe"]
        if name.lower() in {n.lower() for n in self._existing}:
            self._show_err(f"«{name}» уже добавлено в список")
            return
        px: QPixmap | None = info.get("_icon_pixmap")
        if px:
            assets_dir = os.path.join(_PROJECT_DIR, "assets", "wl_images")
            os.makedirs(assets_dir, exist_ok=True)
            icon_path = os.path.join(assets_dir, f"{name}.png")
            if not os.path.isfile(icon_path):
                px.save(icon_path, "PNG")
        self.process_selected.emit(name, exe, px)
        self._on_close()

    def _show_err(self, msg: str) -> None:
        self._err_lbl.setText(msg)
        self._err_lbl.setVisible(True)
        QTimer.singleShot(3200, lambda: self._err_lbl.setVisible(False))

    def _on_close(self) -> None:
        try:
            ThemeManager.instance().theme_changed.disconnect(self._on_theme_changed)
        except Exception:
            pass
        self.closed.emit()

    def _on_theme_changed(self, _c: QColor) -> None:
        self._restyle_search()

    def _restyle_search(self) -> None:
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: rgba({int(r*0.18)},{int(g*0.10)},{int(b*0.22)},120);
                border: 1px solid rgba({int(r*0.60)},{int(g*0.38)},{int(b*0.65)},100);
                border-radius: 10px;
                color: rgba(220,210,255,220);
                padding: 0 12px;
            }}
            QLineEdit:focus {{
                border-color: rgba({int(r*0.85)},{int(g*0.55)},{int(b*0.90)},180);
                background: rgba({int(r*0.22)},{int(g*0.13)},{int(b*0.27)},140);
            }}
        """)

    # ── Рисуем затемнение фона ───────────────────────────

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(4, 2, 14, 205))

    # ── Клик вне карточки — закрыть ─────────────────────

    def mousePressEvent(self, e) -> None:
        if not self._card.geometry().contains(e.pos()):
            self._on_close()
        else:
            super().mousePressEvent(e)


# ══════════════════════════════════════════════════════════
#  ГЛАВНАЯ СТРАНИЦА БЕЛЫХ СПИСКОВ
# ══════════════════════════════════════════════════════════

class WhitelistPage(QWidget):
    """
    Страница белых списков.

    Левая колонка — «популярные» приложения из apps.json (с чекбоксами).
    Правая колонка — добавленные приложения с ToggleSwitch (включить/выключить в VPN).
    Сверху — строка поиска по обеим колонкам.

    При активном VPN все элементы блокируются и применяется opacity=0.45.
    """

    go_back = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ── Состояние ────────────────────────────────────
        self._popular_apps: list[str]              = [a["name"] for a in load_apps_json()]
        self._added_order:  list[str]              = WhitelistState.get_added_order()
        self._enabled_set:  set[str]               = set(WhitelistState.get_enabled())
        self._pop_rows:     dict[str, PopularAppRow]  = {}
        self._added_rows:   dict[str, AddedAppRow]    = {}
        self._vpn_active:   bool                   = False
        self._overlay:      AddProcessOverlay | None = None

        # ── Корневой layout ──────────────────────────────
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Контент-виджет: к нему применяем блюр при открытии оверлея
        self._content_widget = QWidget(self)
        self._content_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        root.addWidget(self._content_widget)

        croot = QVBoxLayout(self._content_widget)
        croot.setContentsMargins(18, 14, 18, 14)
        croot.setSpacing(10)
        croot.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Заголовок
        title = QLabel("Белые списки")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: rgba(232,226,255,242); background: transparent;")
        croot.addWidget(title)

        # ── Строка поиска ────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍  Поиск приложения…")
        self._search_edit.setFont(QFont("Segoe UI", 13))
        self._search_edit.setFixedHeight(38)
        self._search_edit.textChanged.connect(self._on_search)
        search_row.addWidget(self._search_edit, 1)

        self._clear_btn = QPushButton("✕")
        self._clear_btn.setFixedSize(38, 38)
        self._clear_btn.setFont(QFont("Segoe UI", 11))
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setToolTip("Очистить поиск")
        self._clear_btn.setStyleSheet(themed_btn_ss())
        self._clear_btn.clicked.connect(self._search_edit.clear)
        search_row.addWidget(self._clear_btn)
        search_row.addStretch(1)

        croot.addLayout(search_row)
        self._restyle_search(ThemeManager.instance().color())

        # ── Две колонки ──────────────────────────────────
        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(10)

        # Колонка 1: популярные приложения
        col1_card = GlassCard(radius=12, alpha=178)
        col1_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        col1_vl = QVBoxLayout(col1_card)
        col1_vl.setContentsMargins(0, 0, 0, 4)
        col1_vl.setSpacing(0)

        col1_hdr = _PanelHeader("Популярные приложения", add_btn=True)
        self._add_app_btn = col1_hdr.plus_btn()
        if self._add_app_btn:
            self._add_app_btn.clicked.connect(self._open_add_overlay)
        col1_vl.addWidget(col1_hdr)

        self._scroll1 = QScrollArea()
        self._scroll1.setWidgetResizable(True)
        self._scroll1.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll1.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll1.setStyleSheet(scrollbar_ss())

        cw1 = QWidget()
        cw1.setObjectName("sc")
        cw1.setStyleSheet("background: transparent;")
        self._col1_layout = QVBoxLayout(cw1)
        self._col1_layout.setContentsMargins(4, 4, 4, 4)
        self._col1_layout.setSpacing(2)

        for app_name in self._popular_apps:
            checked = app_name in self._added_order
            row     = PopularAppRow(app_name, checked)
            row.check_changed.connect(self._on_check_changed)
            self._col1_layout.addWidget(row)
            self._pop_rows[app_name] = row

        self._col1_layout.addStretch()
        self._scroll1.setWidget(cw1)
        col1_vl.addWidget(self._scroll1, 1)
        cols_layout.addWidget(col1_card, 1)

        # Колонка 2: добавленные приложения
        col2_card = GlassCard(radius=12, alpha=178)
        col2_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        col2_vl = QVBoxLayout(col2_card)
        col2_vl.setContentsMargins(0, 0, 0, 4)
        col2_vl.setSpacing(0)

        col2_hdr = _PanelHeader("Добавленные приложения", add_btn=False)
        col2_vl.addWidget(col2_hdr)

        self._scroll2 = QScrollArea()
        self._scroll2.setWidgetResizable(True)
        self._scroll2.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll2.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll2.setStyleSheet(scrollbar_ss())

        cw2 = QWidget()
        cw2.setObjectName("sc")
        cw2.setStyleSheet("background: transparent;")
        self._col2_layout = QVBoxLayout(cw2)
        self._col2_layout.setContentsMargins(4, 4, 4, 4)
        self._col2_layout.setSpacing(2)

        # Плейсхолдер пустой колонки
        c       = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        self._empty_lbl = QLabel("Нет добавленных приложений")
        self._empty_lbl.setFont(QFont("Segoe UI", 10))
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet(
            f"color: rgba({min(255,int(r*0.60+60))},{min(255,int(g*0.50+60))},"
            f"{min(255,int(b*0.45+80))},100); background: transparent;"
        )
        self._col2_layout.addStretch()
        self._col2_layout.addWidget(self._empty_lbl)
        self._col2_layout.addStretch()

        self._scroll2.setWidget(cw2)
        col2_vl.addWidget(self._scroll2, 1)
        cols_layout.addWidget(col2_card, 1)

        croot.addLayout(cols_layout, 1)

        # Восстанавливаем сохранённые добавленные приложения
        for app_name in self._added_order:
            enabled = app_name in self._enabled_set
            self._insert_added_row(app_name, enabled, save=False)

        ThemeManager.instance().connect_theme(self, self._on_theme_changed)
        ThemeManager.instance().connect_theme(self, lambda c: self._restyle_search(c))

    # ── Сохранение состояния ─────────────────────────────

    def _save_state(self) -> None:
        """Сохраняет текущий состав колонки 2 в whitelist_state.json и settings.json."""
        enabled = [n for n, row in self._added_rows.items() if row.is_enabled()]
        WhitelistState.set_state(self._added_order, enabled)

        exe_list: list[str] = []
        for name in self._added_order:
            row = self._added_rows.get(name)
            if row and row.is_enabled():
                exe_list.append(APP_EXE_MAP.get(name, name + ".exe"))
        AppSettings.set_apps(exe_list)

    # ── Логика добавления / удаления ─────────────────────

    def _on_check_changed(self, name: str, checked: bool) -> None:
        if checked:
            if name not in self._added_order:
                self._added_order.insert(0, name)
                self._insert_added_row(name, enabled=False, save=True)
        else:
            if name in self._added_rows:
                row = self._added_rows[name]
                if row.is_enabled():
                    row.set_enabled(False)
                self._remove_added_row(name, save=True)

    def _insert_added_row(self, name: str, enabled: bool, save: bool) -> None:
        """Вставляет строку в начало колонки 2."""
        row = AddedAppRow(name, enabled)
        row._toggle.toggled.connect(lambda _v: self._save_state())
        self._added_rows[name] = row
        self._col2_layout.insertWidget(0, row)
        self._empty_lbl.setVisible(False)
        if save:
            self._save_state()

    def _remove_added_row(self, name: str, save: bool) -> None:
        row = self._added_rows.pop(name, None)
        if row:
            self._col2_layout.removeWidget(row)
            row.deleteLater()
        if name in self._added_order:
            self._added_order.remove(name)
        if not self._added_rows:
            self._empty_lbl.setVisible(True)
        if save:
            self._save_state()

    # ── Блокировка при активном VPN ──────────────────────

    def set_vpn_active(self, active: bool) -> None:
        """Блокирует/разблокирует все элементы страницы при включении/выключении VPN."""
        self._vpn_active = active
        if active and self._overlay:
            self._close_overlay()
        tip = "Сначала отключите VPN" if active else ""
        for row in self._pop_rows.values():
            row.setEnabled(not active)
            row.setToolTip(tip)
        for row in self._added_rows.values():
            row.setEnabled(not active)
            row.setToolTip(tip)
        self._search_edit.setEnabled(not active)
        self._clear_btn.setEnabled(not active)
        if self._add_app_btn:
            self._add_app_btn.setEnabled(not active)
            self._add_app_btn.setToolTip(tip or "Добавить приложение")

        self._content_widget.setGraphicsEffect(None)
        if active:
            eff = QGraphicsOpacityEffect(self._content_widget)
            eff.setOpacity(0.45)
            self._content_widget.setGraphicsEffect(eff)

    # ── Поиск ────────────────────────────────────────────

    def _on_search(self, text: str) -> None:
        q = text.strip().lower()
        for name, row in self._pop_rows.items():
            row.setVisible(not q or q in name.lower())
        for name, row in self._added_rows.items():
            row.setVisible(not q or q in name.lower())

    # ── Тема ─────────────────────────────────────────────

    def _restyle_search(self, c: QColor) -> None:
        r, g, b = c.red(), c.green(), c.blue()
        self._search_edit.setStyleSheet(f"""
            QLineEdit {{
                background: rgba({int(r*0.18)},{int(g*0.10)},{int(b*0.22)},120);
                border: 1px solid rgba({int(r*0.60)},{int(g*0.38)},{int(b*0.65)},100);
                border-radius: 10px;
                color: rgba(220,210,255,220);
                padding: 0 14px;
                selection-background-color: rgba({int(r*0.70)},{int(g*0.42)},{int(b*0.74)},160);
            }}
            QLineEdit:focus {{
                border-color: rgba({int(r*0.85)},{int(g*0.55)},{int(b*0.90)},180);
                background: rgba({int(r*0.22)},{int(g*0.13)},{int(b*0.27)},140);
            }}
        """)

    def _on_theme_changed(self, c: QColor) -> None:
        self._scroll1.setStyleSheet(scrollbar_ss())
        self._scroll2.setStyleSheet(scrollbar_ss())
        self._clear_btn.setStyleSheet(themed_btn_ss())
        r, g, b = c.red(), c.green(), c.blue()
        self._empty_lbl.setStyleSheet(
            f"color: rgba({min(255,int(r*0.60+60))},{min(255,int(g*0.50+60))},"
            f"{min(255,int(b*0.45+80))},100); background: transparent;"
        )

    # ── Оверлей ──────────────────────────────────────────

    def _open_add_overlay(self) -> None:
        if self._vpn_active or self._overlay:
            return
        blur = QGraphicsBlurEffect(self._content_widget)
        blur.setBlurRadius(12)
        self._content_widget.setGraphicsEffect(blur)
        self._content_widget.setEnabled(False)

        existing = set(self._pop_rows.keys()) | set(self._added_rows.keys())
        overlay  = AddProcessOverlay(existing, parent=self)
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.process_selected.connect(self._on_process_selected)
        overlay.closed.connect(self._close_overlay)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _close_overlay(self) -> None:
        if self._overlay:
            self._overlay.hide()
            self._overlay.deleteLater()
            self._overlay = None
        self._content_widget.setGraphicsEffect(None)
        self._content_widget.setEnabled(True)

    def _on_process_selected(self, name: str, exe: str, px) -> None:
        """Добавляет новый процесс в колонку 1 и в apps.json."""
        if name in self._pop_rows:
            return

        ok = _add_app_to_json(name, exe)
        if not ok:
            # Запись уже есть — обновляем маппинг
            from ui.config import _reload_app_exe_map
            _reload_app_exe_map()

        if name not in self._popular_apps:
            self._popular_apps.append(name)

        checked = name in self._added_order
        row     = PopularAppRow(name, checked)
        row.check_changed.connect(self._on_check_changed)
        count = self._col1_layout.count()
        self._col1_layout.insertWidget(count - 1, row)
        self._pop_rows[name] = row

        self._close_overlay()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self._overlay:
            self._overlay.setGeometry(0, 0, self.width(), self.height())