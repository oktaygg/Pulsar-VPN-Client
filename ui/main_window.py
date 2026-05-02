# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
ui/main_window.py — главное окно приложения.

Содержит:
  - SideNav          — боковая панель навигации с иконками.
  - RoundedMenu      — QMenu с закруглёнными углами (для трея).
  - MainWindow       — главное окно: тайтлбар, стек страниц, трей,
                       resize-логика, фон, сохранение/восстановление настроек.

Зависимости:
    ui.theme         → ThemeManager
    ui.config        → PulsarConfig
    ui.widgets       → (косвенно, через страницы)
    ui.servers_page  → ServersPage
    ui.settings_page → SettingsPage
    ui.whitelist_page→ WhitelistPage
    ui.info_page     → InfoPage
"""

import ctypes
import logging
import os

_log = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon, QMenu, QApplication,
)
from PyQt6.QtCore import (
    Qt, QRect, QRectF, QSize,
    pyqtSignal, QTimer, QPoint, QEvent,
)
from PyQt6.QtGui import (
    QColor, QPainter, QBrush, QPen,
    QLinearGradient, QRadialGradient,
    QFont, QPixmap, QPainterPath,
    QMouseEvent, QIcon, QAction,
)

from ui.theme import ThemeManager
from ui.config import PulsarConfig
from ui.servers_page import ServersPage
from ui.settings_page import SettingsPage
from ui.whitelist_page import WhitelistPage
from ui.info_page import InfoPage

_UI_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_UI_DIR)


# ══════════════════════════════════════════════════════════
#  WINDOWS ACRYLIC — размытие за окном
# ══════════════════════════════════════════════════════════

def enable_blur_behind(hwnd: int) -> None:
    """Включает Acrylic-размытие за окном через SetWindowCompositionAttribute."""
    try:
        class _AP(ctypes.Structure):
            _fields_ = [
                ("AccentState",   ctypes.c_uint),
                ("AccentFlags",   ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId",   ctypes.c_uint),
            ]
        class _WD(ctypes.Structure):
            _fields_ = [
                ("Attribute",   ctypes.c_int),
                ("pData",       ctypes.c_void_p),
                ("ulDataSize",  ctypes.c_ulong),
            ]
        a = _AP()
        a.AccentState   = 4
        a.AccentFlags   = 2
        a.GradientColor = 0xCC0A0518
        d = _WD()
        d.Attribute     = 19
        d.pData         = ctypes.cast(ctypes.pointer(a), ctypes.c_void_p)
        d.ulDataSize    = ctypes.sizeof(a)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.pointer(d))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


# ══════════════════════════════════════════════════════════
#  БОКОВАЯ НАВИГАЦИЯ
# ══════════════════════════════════════════════════════════

class SideNav(QWidget):
    """
    Вертикальная панель навигации с иконками-кнопками.
    """

    page_changed = pyqtSignal(int)

    _NAV_ITEMS = [
        (0, "main.png"),
        (1, "settings.png"),
        (3, "white_list.png"),
    ]
    _INFO_ITEM = (4, "info.png")
    _ICON_SIZE = 24

    _ICON_CACHE: dict[str, QIcon] = {}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(62)
        self._active = 0
        self._btns: list[tuple[QPushButton, int]] = []

        vl = QVBoxLayout(self)
        vl.setContentsMargins(8, 10, 8, 14)
        vl.setSpacing(6)
        for idx, fname in self._NAV_ITEMS:
            vl.addWidget(self._mk(idx, fname))
        vl.addStretch()
        vl.addWidget(self._mk(*self._INFO_ITEM))

        self._apply_styles()
        ThemeManager.instance().connect_theme(self, lambda _c: self._apply_styles())

    def set_active(self, idx: int) -> None:
        """Переключает визуально активную кнопку."""
        self._active = idx
        self._apply_styles()

    @classmethod
    def _get_icon(cls, fname: str) -> QIcon:
        """
        Возвращает белую иконку из кеша.
        При первом вызове строит через QPainter (SourceIn-compositing).
        """
        if fname in cls._ICON_CACHE:
            return cls._ICON_CACHE[fname]

        base = _PROJECT_DIR
        path = os.path.join(base, "assets", "app_images", fname)
        src  = QPixmap(path)
        if src.isNull():
            cls._ICON_CACHE[fname] = QIcon()
            return QIcon()

        src = src.scaled(
            cls._ICON_SIZE, cls._ICON_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Рисуем белый прямоугольник через SourceIn — форма иконки сохраняется
        result = QPixmap(src.size())
        result.fill(Qt.GlobalColor.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, src)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), QColor(255, 255, 255))
        painter.end()

        icon = QIcon(result)
        cls._ICON_CACHE[fname] = icon
        return icon

    def _mk(self, idx: int, fname: str) -> QPushButton:
        """Создаёт одну кнопку навигации."""
        btn = QPushButton()
        btn.setFixedSize(46, 46)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(self._ICON_SIZE, self._ICON_SIZE))
        btn.setIcon(self._get_icon(fname))
        btn.clicked.connect(lambda _c, i=idx: self._on_click(i))
        self._btns.append((btn, idx))
        return btn

    def _on_click(self, idx: int) -> None:
        if idx >= 0:
            self.page_changed.emit(idx)

    def _apply_styles(self) -> None:
        """Перекрашивает кнопки: активная — с акцентным фоном, остальные — прозрачные."""
        c = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()
        for btn, idx in self._btns:
            if idx == self._active and idx >= 0:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba({int(r*0.83)},{int(g*0.48)},{int(b*0.86)},160);
                        border: 1px solid rgba({int(r*0.93+10)},{int(g*0.58+10)},{int(b*0.99)},180);
                        border-radius: 10px;
                    }}
                    QPushButton:hover {{
                        background: rgba({int(r*0.94)},{int(g*0.56)},{int(b*0.92)},180);
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; border: none;
                        border-radius: 10px; opacity: 0.55;
                    }}
                    QPushButton:hover {{
                        background: rgba({int(r*0.68)},{int(g*0.40)},{int(b*0.70)},80);
                    }}
                """)


# ══════════════════════════════════════════════════════════
#  МЕНЮ ТРЕЯ С ЗАКРУГЛЁННЫМИ УГЛАМИ
# ══════════════════════════════════════════════════════════

class RoundedMenu(QMenu):
    """
    Работает через FramelessWindowHint + WA_TranslucentBackground +
    собственный paintEvent с закруглённым фоном.
    """

    RADIUS = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._bg_color     = QColor(22, 10, 42, 250)
        self._border_color = QColor(80, 50, 120, 120)

    def set_colors(self, bg: QColor, border: QColor) -> None:
        """Обновляет цвет фона и обводки (вызывается при смене темы)."""
        self._bg_color     = bg
        self._border_color = border
        self.update()

    def mousePressEvent(self, e: QMouseEvent) -> None:
        # Принимаем ЛКМ и ПКМ — выделяем пункт под курсором
        action = self.actionAt(e.position().toPoint())
        if action and action.isEnabled():
            self.setActiveAction(action)
        e.accept()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        # На отпускании активируем пункт и закрываем меню
        action = self.actionAt(e.position().toPoint())
        if action and action.isEnabled():
            self.hide()
            action.trigger()
            e.accept()
            return
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.hide()
        e.accept()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        # Подсвечиваем пункт под курсором при движении
        action = self.actionAt(e.position().toPoint())
        if action:
            self.setActiveAction(action)
        e.accept()   # не пробрасываем — иначе MainWindow двигает

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        p.setClipPath(path)
        p.fillPath(path, QBrush(self._bg_color))
        p.setClipping(False)

        p.setPen(QPen(self._border_color, 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        p.end()

        super().paintEvent(event)


# ══════════════════════════════════════════════════════════
#  ГЛАВНОЕ ОКНО
# ══════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    """
    Главное окно приложения.

    Отвечает за:
      - Frameless-окно с пользовательским тайтлбаром (перетаскивание, resize, максимизация).
      - Стек страниц (ServersPage, SettingsPage, WhitelistPage, InfoPage).
      - Системный трей с RoundedMenu.
      - Фон (QPixmap или градиент), сохранение/восстановление настроек через PulsarConfig.
    """

    _RESIZE_MARGIN = 6   # px от края — зона захвата для ресайза

    _EDGE_CURSORS = {
        "n":  Qt.CursorShape.SizeVerCursor,
        "s":  Qt.CursorShape.SizeVerCursor,
        "w":  Qt.CursorShape.SizeHorCursor,
        "e":  Qt.CursorShape.SizeHorCursor,
        "nw": Qt.CursorShape.SizeFDiagCursor,
        "se": Qt.CursorShape.SizeFDiagCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor,
        "sw": Qt.CursorShape.SizeBDiagCursor,
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pulsar VPN")

        _icon_path = os.path.join(
            _PROJECT_DIR, "assets", "app_images", "icon.ico"
        )
        if os.path.isfile(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        self.setMinimumSize(800, 540)
        self.resize(950, 630)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        self._bg_pixmap:        QPixmap | None = None
        self._drag_pos:         QPoint  | None = None
        self._is_maximized:     bool = False
        self._resize_edge_dir:  str  = ""
        self._resize_start_pos: QPoint = QPoint()
        self._resize_start_geo: QRect  = QRect()

        # Путь к дефолтному фону — не удаляется при смене
        self._default_bg_path: str = os.path.join(
            _PROJECT_DIR, "assets", "app_images", "pulsar.jpg"
        )
        # Текущий пользовательский фон (не дефолтный) — удаляется при замене
        self._current_user_bg: str = ""

        # ── Восстанавливаем состояние из pulsar_config.json ──────
        cfg = PulsarConfig.load()

        # Цвет темы
        _tc = QColor(cfg.get("theme_color", "#2d9cdb"))
        ThemeManager.instance().set_color(_tc if _tc.isValid() else QColor(45, 156, 219))

        # Кастомный цвет — передадим SettingsPage после её создания
        self._saved_custom_color: str = cfg.get("custom_color", "#2d9cdb")

        # Фон
        if bool(cfg.get("bg_enabled", True)):
            _bp = cfg.get("background_path", "")
            if _bp and os.path.isfile(str(_bp)):
                _px = QPixmap(str(_bp))
                if not _px.isNull():
                    self._bg_pixmap = _px
                    try:
                        if os.path.abspath(str(_bp)) != os.path.abspath(self._default_bg_path):
                            self._current_user_bg = str(_bp)
                    except (ValueError, OSError):
                        pass
            # Путь пустой или файл не найден — грузим дефолтный фон (pulsar.png).
            # Актуально при первом запуске, когда pulsar_config.json ещё не создан.
            if self._bg_pixmap is None and os.path.isfile(self._default_bg_path):
                _px = QPixmap(self._default_bg_path)
                if not _px.isNull():
                    self._bg_pixmap = _px
                    PulsarConfig.set_many(
                        background_path=self._default_bg_path,
                        bg_enabled=True,
                    )

        # Геометрия окна
        _wx = int(cfg.get("window_x", -1))
        _wy = int(cfg.get("window_y", -1))
        _ww = int(cfg.get("window_w", 950))
        _wh = int(cfg.get("window_h", 630))
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            if _ww >= sg.width() or _wh >= sg.height():
                _ww, _wh = 950, 630
            _ww = max(800, min(_ww, sg.width()  - 40))
            _wh = max(540, min(_wh, sg.height() - 40))
        self.resize(_ww, _wh)
        if _wx >= 0 and _wy >= 0:
            self.move(_wx, _wy)

        ThemeManager.instance().connect_theme(self, self._on_theme_changed)

        # ── Системный трей ──────────────────────────────────────
        # _tray_host — Tool-окно без FramelessWindowHint:
        # Windows корректно отдаёт ему фокус, ЛКМ в меню работает.
        self._tray_host = QWidget(None, Qt.WindowType.Tool)
        self._tray_host.setWindowOpacity(0)
        self._tray_host.resize(1, 1)
        self._tray_host.move(-32000, -32000)
        self._tray_host.show()

        self._tray = QSystemTrayIcon(self._tray_host)
        _tray_icon_path = os.path.join(
            _PROJECT_DIR, "assets", "app_images", "icon.ico"
        )
        if os.path.isfile(_tray_icon_path):
            self._tray.setIcon(QIcon(_tray_icon_path))
        else:
            app = QApplication.instance()
            if isinstance(app, QApplication):
                self._tray.setIcon(app.windowIcon())
        self._tray.setToolTip("Pulsar VPN")

        self._tray_menu = RoundedMenu(self._tray_host)
        self._update_tray_menu_style()
        _act_open = QAction("  Открыть",  self._tray_host)
        _act_quit = QAction("  Закрыть",  self._tray_host)
        _act_open.triggered.connect(self._show_from_tray)
        _act_quit.triggered.connect(self._quit_app)
        self._tray_menu.addAction(_act_open)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(_act_quit)
        self._tray.setContextMenu(self._tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        ThemeManager.instance().connect_theme(self._tray_host, self._update_tray_menu_style)

        # ── Центральный виджет ──────────────────────────────────
        central = QWidget(self)
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(central)
        self.setMouseTracking(True)
        central.setMouseTracking(True)
        QApplication.instance().installEventFilter(self)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Тайтлбар ─────────────────────────────────────────────
        tb = QWidget()
        tb.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        tb.setFixedHeight(36)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(14, 0, 6, 0)
        tbl.setSpacing(0)
        tbl.addStretch()

        self._tb_btns: list[tuple[QPushButton, str]] = []

        for sym, act, size in [("‒", "min", 16), ("▢", "max", 20), ("✕", "close", 16)]:
            b = QPushButton(sym)
            b.setFixedSize(40, 30)
            b.setFont(QFont("Segoe UI", size))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFlat(True)

            self._tb_btns.append((b, act))

            if act == "min":
                b.clicked.connect(self.showMinimized)
            elif act == "max":
                b.clicked.connect(self._toggle_max)
            else:
                b.clicked.connect(self._hide_to_tray)
            tbl.addWidget(b)

        self._apply_tb_styles()

        tb.mousePressEvent       = self._tb_press
        tb.mouseMoveEvent        = self._tb_move
        tb.mouseReleaseEvent     = lambda _e: setattr(self, "_drag_pos", None)
        tb.mouseDoubleClickEvent = lambda _e: self._toggle_max()
        root.addWidget(tb)

        # ── Тело: навигация + стек страниц ───────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._nav = SideNav()
        self._nav.page_changed.connect(self._on_nav)
        body.addWidget(self._nav)

        self._stack = QStackedWidget()
        self._stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._stack.setStyleSheet("background: transparent;")

        # Страницы
        self._p_servers = ServersPage()
        self._p_servers.open_whitelist.connect(lambda: self._on_nav(3))
        self._p_servers.vpn_state_changed.connect(self._on_vpn_state_changed)

        self._p_settings = SettingsPage()
        # Восстанавливаем кастомный цвет
        _cc = QColor(self._saved_custom_color)
        if _cc.isValid():
            self._p_settings._custom_color = _cc  # noqa: SLF001
            self._p_settings._refresh_preset_selection(ThemeManager.instance().color())  # noqa: SLF001
        # Восстанавливаем состояние тоггла и путь к фону
        _cfg2 = PulsarConfig.load()
        _bg_en = bool(_cfg2.get("bg_enabled", True))
        self._p_settings._bg_enabled         = _bg_en  # noqa: SLF001
        self._p_settings._bg_toggle._checked = _bg_en  # noqa: SLF001
        self._p_settings._bg_toggle._pos     = 1.0 if _bg_en else 0.0  # noqa: SLF001
        self._p_settings._bg_toggle._target  = self._p_settings._bg_toggle._pos  # noqa: SLF001
        self._p_settings._last_bg_path       = _cfg2.get("background_path", "")  # noqa: SLF001
        self._p_settings.bg_changed.connect(self._save_bg)
        self._p_settings.bg_reset.connect(self._reset_bg)
        self._p_settings.bg_default.connect(self._set_default_bg)
        self._p_settings.theme_changed.connect(self._on_theme_changed)

        _dummy = QWidget()
        _dummy.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._p_whitelist = WhitelistPage()
        self._p_whitelist.go_back.connect(lambda: self._on_nav(0))

        self._p_info = InfoPage()

        self._stack.addWidget(self._p_servers)   # index 0
        self._stack.addWidget(self._p_settings)  # index 1
        self._stack.addWidget(_dummy)             # index 2 (зарезервирован)
        self._stack.addWidget(self._p_whitelist)  # index 3
        self._stack.addWidget(self._p_info)       # index 4
        self._stack.setCurrentIndex(0)

        body.addWidget(self._stack)
        root.addLayout(body)

        QTimer.singleShot(150, self._apply_blur)

    def _apply_tb_styles(self) -> None:
        """Перекрашивает кнопки тайтлбара под цвет темы (приглушённые тона)."""
        c = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()

        # Размеры шрифта: min=16, max=18, close=15
        font_sizes = {"min": 18, "max": 24, "close": 13}

        for btn, act in self._tb_btns:
            is_x = (act == "close")
            fs = font_sizes.get(act, 12)

            if is_x:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; border: none;
                        color: rgba({int(r * 0.65)},{int(g * 0.50)},{int(b * 0.60)},160);
                        border-radius: 6px;
                        font-size: {fs}px;
                    }}
                    QPushButton:hover {{
                        background: rgba(182,38,38,130);
                        color: rgba(255,128,128,240);
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent; border: none;
                        color: rgba({int(r * 0.65)},{int(g * 0.50)},{int(b * 0.60)},160);
                        border-radius: 6px;
                        font-size: {fs}px;
                    }}
                    QPushButton:hover {{
                        background: rgba({int(r * 0.30)},{int(g * 0.18)},{int(b * 0.32)},100);
                        color: rgba({int(r * 0.85)},{int(g * 0.68)},{int(b * 0.82)},210);
                    }}
                """)

    # ── Навигация ─────────────────────────────────────────

    def _on_nav(self, idx: int) -> None:
        """Переключает страницу. Блокирует вайтлист если VPN активен."""
        self._p_servers.close_dialog()

        if idx == 3 and (self._p_servers._connected or self._p_servers._connecting):  # noqa: SLF001
            self._p_servers._vpn_lock_warning()  # noqa: SLF001
            return
        if idx != 3 and self._p_whitelist._overlay:  # noqa: SLF001
            self._p_whitelist._close_overlay()  # noqa: SLF001

        self._stack.setCurrentIndex(idx)
        self._nav.set_active(idx)

    def _on_vpn_state_changed(self, connected: bool) -> None:
        self._p_whitelist.set_vpn_active(connected)

    # ── Тайтлбар — перетаскивание ─────────────────────────

    def _tb_press(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def _tb_move(self, e: QMouseEvent) -> None:
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    # ── Resize по краям окна ─────────────────────────────

    def _resize_edge(self, pos: QPoint) -> str:
        """Определяет направление захвата края окна по позиции курсора."""
        m  = self._RESIZE_MARGIN
        tb = 36
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        left    = x < m
        right   = x > w - m
        top     = y < m
        top_tb  = y < tb and (left or right)
        bottom  = y > h - m
        if (top or top_tb) and left:  return "nw"
        if (top or top_tb) and right: return "ne"
        if bottom and left:           return "sw"
        if bottom and right:          return "se"
        if top:    return "n"
        if bottom: return "s"
        if left:   return "w"
        if right:  return "e"
        return ""

    def eventFilter(self, obj, e) -> bool:
        # Игнорируем события пока меню трея открыто
        if self._tray_menu.isVisible():
            return super().eventFilter(obj, e)

        t = e.type()
        if t == QEvent.Type.MouseMove:
            gp = e.globalPosition().toPoint()
            lp = self.mapFromGlobal(gp)
            if self._resize_edge_dir:
                dx = gp.x() - self._resize_start_pos.x()
                dy = gp.y() - self._resize_start_pos.y()
                g  = QRect(self._resize_start_geo)
                min_w, min_h = self.minimumWidth(), self.minimumHeight()
                d = self._resize_edge_dir
                if "e" in d: g.setRight (max(g.left() + min_w, g.right()  + dx))
                if "s" in d: g.setBottom(max(g.top()  + min_h, g.bottom() + dy))
                if "w" in d: g.setLeft  (min(g.right() - min_w, g.left()  + dx))
                if "n" in d: g.setTop   (min(g.bottom() - min_h, g.top()  + dy))
                self.setGeometry(g)
                return True
            else:
                edge = self._resize_edge(lp)
                self.setCursor(self._EDGE_CURSORS.get(edge, Qt.CursorShape.ArrowCursor))

        elif t == QEvent.Type.MouseButtonPress:
            if e.button() == Qt.MouseButton.LeftButton:
                gp   = e.globalPosition().toPoint()
                lp   = self.mapFromGlobal(gp)
                edge = self._resize_edge(lp)
                if edge:
                    self._resize_edge_dir  = edge
                    self._resize_start_pos = gp
                    self._resize_start_geo = self.geometry()
                    return True
                else:
                    self._resize_edge_dir = ""

        elif t == QEvent.Type.MouseButtonRelease:
            if self._resize_edge_dir:
                self._resize_edge_dir = ""
                self.setCursor(Qt.CursorShape.ArrowCursor)
                return True

        return super().eventFilter(obj, e)

    def mousePressEvent(self,   e: QMouseEvent) -> None: super().mousePressEvent(e)
    def mouseMoveEvent(self,    e: QMouseEvent) -> None: super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._resize_edge_dir = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(e)

    def _toggle_max(self) -> None:
        """Переключает между максимизацией и нормальным размером."""
        if self._is_maximized:
            self._is_maximized = False
            self.showNormal()
        else:
            self._is_maximized = True
            self.showMaximized()

    # ── Blur / DWM ────────────────────────────────────────

    def _apply_blur(self) -> None:
        """Включает Acrylic-размытие и скругление рамки DWM."""
        hwnd = int(self.winId())
        try:
            enable_blur_behind(hwnd)
            v = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd, 33, ctypes.byref(v), ctypes.sizeof(v)
            )
        except (AttributeError, OSError) as e:
            _log.debug("DWM: %s", e)

    # ── Трей ──────────────────────────────────────────────

    def _hide_to_tray(self) -> None:
        """Скрывает окно в трей."""
        self.hide()

    def _show_from_tray(self) -> None:
        """Восстанавливает окно из трея."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _update_tray_menu_style(self, c: QColor | None = None) -> None:
        """Обновляет стиль контекстного меню трея под текущую тему."""
        if c is None:
            c = ThemeManager.instance().color()
        r, g, b = c.red(), c.green(), c.blue()

        bg_qcolor     = QColor(max(18, int(r*0.13)), max(9, int(g*0.08)), max(35, int(b*0.20)), 250)
        border_qcolor = QColor(int(r*0.52), int(g*0.28), int(b*0.55), 100)
        self._tray_menu.set_colors(bg_qcolor, border_qcolor)

        bghover = f'rgba({int(r*0.42)},{int(g*0.24)},{int(b*0.46)},190)'
        sep     = f'rgba({int(r*0.38)},{int(g*0.20)},{int(b*0.42)},70)'
        txt     = 'rgba(220,228,255,215)'
        txth    = 'rgba(255,255,255,255)'
        self._tray_menu.setStyleSheet(
            "QMenu {"
            "  background-color: transparent;"
            "  border: none;"
            "  padding: 5px 0px;"
            "  font-family: 'Segoe UI';"
            "  font-size: 13px;"
            "}"
            "QMenu::item {"
            "  padding: 8px 24px 8px 16px;"
            "  border-radius: 6px;"
            "  margin: 1px 5px;"
            f" color: {txt};"
            "}"
            "QMenu::item:selected {"
            f" background-color: {bghover};"
            f" color: {txth};"
            "}"
            "QMenu::separator {"
            "  height: 1px;"
            f" background: {sep};"
            "  margin: 4px 12px;"
            "}"
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Одиночный/двойной ЛКМ по иконке — переключает видимость окна."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible():
                self._hide_to_tray()
            else:
                self._show_from_tray()

    def _quit_app(self) -> None:
        """Полное закрытие приложения из трея."""
        try:
            if hasattr(self, "_p_servers"):
                self._p_servers.force_stop_vpn()
        except (RuntimeError, AttributeError):
            pass

        if not self._is_maximized:
            pos = self.pos()
            sz  = self.size()
            PulsarConfig.set_many(
                window_x=pos.x(),
                window_y=pos.y(),
                window_w=sz.width(),
                window_h=sz.height(),
            )

        self._tray.hide()
        if hasattr(self, "_tray_host"):
            self._tray_host.hide()
        QApplication.instance().quit()

    def closeEvent(self, e) -> None:
        """Перехватываем закрытие — прячем в трей вместо выхода."""
        e.ignore()
        self._hide_to_tray()

    # ── Тема ──────────────────────────────────────────────

    def _on_theme_changed(self, c: QColor) -> None:
        """Сохраняет новый цвет темы и кастомный цвет, перерисовывает окно."""
        PulsarConfig.set_many(
            theme_color=c.name(),
            custom_color=self._p_settings._custom_color.name(),  # noqa: SLF001
        )
        self._apply_tb_styles()
        self.update()

    # ── Фон ───────────────────────────────────────────────

    def _is_default_bg(self, path: str) -> bool:
        """True если path — дефолтный фон (pulsar.png)."""
        try:
            return os.path.abspath(path) == os.path.abspath(self._default_bg_path)
        except (ValueError, OSError):
            return False

    def _delete_user_bg_if_needed(self, path: str) -> None:
        """Удаляет пользовательский фон, если он не дефолтный и файл существует."""
        if path and not self._is_default_bg(path):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception as e:
                _log.warning("Не удалось удалить старый фон: %s", e)

    def _save_bg(self, path: str) -> None:
        """Загружает новый фон из path, удаляет предыдущий пользовательский."""
        px = QPixmap(path)
        if not px.isNull():
            self._delete_user_bg_if_needed(self._current_user_bg)
            self._bg_pixmap       = px
            self._current_user_bg = "" if self._is_default_bg(path) else path
            # Не сохраняем пути из _MEIPASS — они временные и меняются при каждом запуске
            import sys as _sys
            _meipass = getattr(_sys, '_MEIPASS', None)
            save_path = "" if (_meipass and _meipass in path) else path
            PulsarConfig.set_many(background_path=save_path, bg_enabled=True)
            self.update()

    def _reset_bg(self) -> None:
        """Выключает фон. Пользовательский файл не удаляется."""
        self._bg_pixmap = None
        PulsarConfig.set_many(background_path="", bg_enabled=False)
        self.update()

    def _set_default_bg(self) -> None:
        """Устанавливает assets/app_images/pulsar.png как фон."""
        if os.path.isfile(self._default_bg_path):
            px = QPixmap(self._default_bg_path)
            if not px.isNull():
                self._delete_user_bg_if_needed(self._current_user_bg)
                self._bg_pixmap       = px
                self._current_user_bg = ""
                # Не сохраняем путь из _MEIPASS — он временный
                import sys as _sys
                _meipass = getattr(_sys, '_MEIPASS', None)
                _save_path = "" if (_meipass and _meipass in self._default_bg_path) else self._default_bg_path
                PulsarConfig.set_many(background_path=_save_path, bg_enabled=True)
                self.update()
                return
        # Файл не найден — убираем фон
        self._delete_user_bg_if_needed(self._current_user_bg)
        self._current_user_bg = ""
        self._bg_pixmap = None
        PulsarConfig.set_many(background_path="", bg_enabled=False)
        self.update()

    def set_background(self, path: str) -> None:
        """Публичный псевдоним для _save_bg (используется снаружи при необходимости)."""
        self._save_bg(path)

    # ── Отрисовка ─────────────────────────────────────────

    def paintEvent(self, _e) -> None:
        """Рисует фон: изображение или цветной градиент в цвет текущей темы."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self.rect()
        rf     = QRectF(rect)
        radius = 11

        clip = QPainterPath()
        clip.addRoundedRect(rf, radius, radius)
        p.setClipPath(clip)

        if self._bg_pixmap:
            sc = self._bg_pixmap.scaled(
                rect.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            ox = (sc.width()  - rect.width())  // 2
            oy = (sc.height() - rect.height()) // 2
            p.drawPixmap(0, 0, sc, ox, oy, rect.width(), rect.height())
            p.fillRect(rect, QColor(7, 3, 18, 152))

        else:
            ac = ThemeManager.instance().color()
            r, g, b = ac.red(), ac.green(), ac.blue()
            g_bg = QLinearGradient(0, 0, rect.width(), rect.height())
            g_bg.setColorAt(0.0, QColor(max(4, int(r*0.054)), max(2, int(g*0.037)), max(14, int(b*0.078))))
            g_bg.setColorAt(0.4, QColor(max(7, int(r*0.10)),  max(3, int(g*0.062)), max(22, int(b*0.133))))
            g_bg.setColorAt(0.8, QColor(max(9, int(r*0.13)),  max(4, int(g*0.087)), max(30, int(b*0.180))))
            g_bg.setColorAt(1.0, QColor(max(5, int(r*0.069)), max(2, int(g*0.037)), max(16, int(b*0.102))))
            p.fillRect(rect, QBrush(g_bg))
            for cx2, cy2, cr2, alpha in [
                (rect.width() * 0.70, rect.height() * 0.28, 188, 35),
                (rect.width() * 0.82, rect.height() * 0.76, 128, 27),
                (rect.width() * 0.18, rect.height() * 0.82, 148, 21),
            ]:
                rg = QRadialGradient(cx2, cy2, cr2)
                rg.setColorAt(0, QColor(int(r*0.75), int(g*0.36), int(b*0.78), alpha))
                rg.setColorAt(1, QColor(0, 0, 0, 0))
                p.fillRect(rect, QBrush(rg))

        # ── ПУЛЬСАР (star.png) — рисуется ВСЕГДА, независимо от фона ──
        if hasattr(self, '_p_servers') and hasattr(self._p_servers, '_pwr'):
            pwr = self._p_servers._pwr
            if pwr.isVisible() and pwr.width() > 0:
                pwr_center = pwr.mapToGlobal(QPoint(pwr.width() // 2, pwr.height() // 2))
                local_center = self.mapFromGlobal(pwr_center)

                star_path = os.path.join(_PROJECT_DIR, "assets", "app_images", "star.png")
                star_px = QPixmap(star_path)
                if not star_px.isNull():
                    p.save()
                    p.setOpacity(0.6)
                    px_x = local_center.x() - star_px.width() // 2 - 90
                    py_y = local_center.y() - star_px.height() // 2 + 24
                    p.drawPixmap(px_x, py_y, star_px)
                    p.restore()

        p.setClipping(False)

        ac2 = ThemeManager.instance().color()
        p.setPen(QPen(
            QColor(int(ac2.red()*0.86), int(ac2.green()*0.54), int(ac2.blue()*0.87), 84),
            1
        ))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rf, radius, radius)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)