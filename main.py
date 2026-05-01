# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
main.py — точка входа приложения Pulsar VPN.

Порядок запуска:
  1. DPI-awareness (Windows).
  2. Проверка прав администратора.
     - Без прав → показываем AdminRequiredDialog, предлагаем UAC-перезапуск.
     - С правами → создаём MainWindow и запускаем цикл событий.
"""

import sys
import ctypes
import os

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QIcon

from ui.config import PulsarConfig
from ui.main_window import MainWindow

# ════ Защита от повторного запуска ════

_THIS_EXE = os.path.basename(sys.executable).lower() if getattr(sys, 'frozen', False) else ""

def _find_existing_window():
    """Ищет уже запущенное окно Pulsar через Win32 API."""
    try:
        hwnd = ctypes.windll.user32.FindWindowW(None, "Pulsar")
        if hwnd:
            # Если окно свёрнуто в трей — восстанавливаем
            if ctypes.windll.user32.IsWindowVisible(hwnd) == 0:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════════
#  ПРОВЕРКА И ЗАПРОС ПРАВ АДМИНИСТРАТОРА
# ══════════════════════════════════════════════════════════

def _is_admin() -> bool:
    """Возвращает True если процесс запущен с правами администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _restart_as_admin() -> None:
    """Перезапускает скрипт/exe с правами администратора через UAC."""
    try:
        exe  = sys.executable
        args = " ".join(f'"{a}"' for a in sys.argv)
        ctypes.windll.shell32.ShellExecuteW(
            None,    # hwnd
            "runas", # verb — запрашивает UAC
            exe,     # file
            args,    # parameters
            None,    # directory
            1,       # SW_NORMAL
        )
    except Exception as e:
        print(f"[Admin] Не удалось перезапустить: {e}")


class AdminRequiredDialog(QWidget):
    """
    Полноэкранный оверлей при отсутствии прав администратора.
    Цвета берутся из сохранённой темы (PulsarConfig).
    """

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("Pulsar")

        _icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "assets", "app_images", "icon.ico",
        )
        if os.path.isfile(_icon_path):
            self.setWindowIcon(QIcon(_icon_path))

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        # Читаем сохранённый цвет темы из конфига
        _hex = PulsarConfig.get("theme_color") or "#2d9cdb"
        c    = QColor(_hex)
        if not c.isValid():
            c = QColor(45, 156, 219)
        r, g, b = c.red(), c.green(), c.blue()

        self._theme_color = c   # сохраняем для paintEvent

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Карточка по центру
        card = QWidget(self)
        card.setFixedWidth(430)
        card.setObjectName("adm_card")
        card.setStyleSheet(
            f"QWidget#adm_card {{"
            f"  background: rgba({max(10,int(r*0.08))},{max(5,int(g*0.05))},{max(20,int(b*0.13))},248);"
            f"  border: 1px solid rgba({int(r*0.52)},{int(g*0.32)},{int(b*0.55)},160);"
            f"  border-radius: 18px;"
            f"}}"
        )

        cl = QVBoxLayout(card)
        cl.setContentsMargins(36, 32, 36, 32)
        cl.setSpacing(14)
        cl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Иконка щита
        shield = QLabel("🛡")
        shield.setFont(QFont("Segoe UI Emoji", 44))
        shield.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shield.setStyleSheet("background: transparent;")
        cl.addWidget(shield)

        # Заголовок
        head = QLabel("Требуются права\nадминистратора")
        head.setFont(QFont("Segoe UI", 17, QFont.Weight.Bold))
        head.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.setStyleSheet(
            f"color: rgba({min(255,int(r*0.70+80))},{min(255,int(g*0.78+60))},{min(255,int(b*0.68+80))},245);"
            f"background: transparent;"
        )
        cl.addWidget(head)

        # Описание
        desc = QLabel(
            "Pulsar VPN использует TUN-интерфейс для туннелирования трафика.\n"
            "Для корректной работы необходимы права администратора."
        )
        desc.setFont(QFont("Segoe UI", 10))
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: rgba({int(r*0.50)+70},{int(g*0.55)+60},{int(b*0.48)+80},190);"
            f"background: transparent;"
        )
        cl.addWidget(desc)
        cl.addSpacing(6)

        # Кнопка перезапуска с правами
        btn_restart = QPushButton("  Перезапустить с правами администратора")
        btn_restart.setFixedHeight(44)
        btn_restart.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.setStyleSheet(f"""
            QPushButton {{
                background: rgba({int(r*0.30)},{int(g*0.19)},{int(b*0.34)},210);
                border: 1px solid rgba({int(r*0.70)},{int(g*0.44)},{int(b*0.74)},200);
                border-radius: 11px;
                color: rgba({min(255,int(r*0.78+42))},{min(255,int(g*0.70+52))},{min(255,int(b*0.74+42))},230);
            }}
            QPushButton:hover {{
                background: rgba({int(r*0.48)},{int(g*0.30)},{int(b*0.52)},235);
                border-color: rgba({int(r*0.92)},{int(g*0.62)},{int(b*0.96)},230);
                color: white;
            }}
            QPushButton:pressed {{
                background: rgba({int(r*0.58)},{int(g*0.36)},{int(b*0.62)},255);
            }}
        """)
        btn_restart.clicked.connect(self._do_restart)
        cl.addWidget(btn_restart)

        # Кнопка «Закрыть»
        btn_close = QPushButton("Закрыть")
        btn_close.setFixedHeight(38)
        btn_close.setFont(QFont("Segoe UI", 10))
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid rgba({int(r*0.38)},{int(g*0.24)},{int(b*0.42)},110);
                border-radius: 10px;
                color: rgba({int(r*0.48)+55},{int(g*0.44)+55},{int(b*0.46)+65},170);
            }}
            QPushButton:hover {{
                background: rgba({int(r*0.18)},{int(g*0.11)},{int(b*0.22)},90);
                border-color: rgba({int(r*0.58)},{int(g*0.38)},{int(b*0.62)},160);
                color: rgba({min(255,int(r*0.72)+50)},{min(255,int(g*0.66)+50)},{min(255,int(b*0.68)+60)},220);
            }}
        """)
        btn_close.clicked.connect(QApplication.instance().quit)
        cl.addWidget(btn_close)

        root.addWidget(card)

    def paintEvent(self, _e) -> None:
        """Полупрозрачный тёмный фон на весь экран."""
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))

    def _do_restart(self) -> None:
        _restart_as_admin()
        QApplication.instance().quit()


# ══════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Проверяем, не запущен ли уже Pulsar
    if _find_existing_window():
        sys.exit(0)
    # 1. DPI-awareness
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    # 2. Создаём QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    _app_icon_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets", "app_images", "icon.ico"
    )
    if os.path.isfile(_app_icon_path):
        app.setWindowIcon(QIcon(_app_icon_path))

    from PyQt6.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(11,  6, 26))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(220, 210, 255))
    pal.setColor(QPalette.ColorRole.Base,            QColor(16,  9, 38))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(22, 13, 50))
    pal.setColor(QPalette.ColorRole.Text,            QColor(210, 200, 240))
    pal.setColor(QPalette.ColorRole.Button,          QColor(26, 15, 52))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(210, 200, 240))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(110, 65, 230))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(pal)

    # 3. Проверка прав администратора
    if not _is_admin():
        dlg = AdminRequiredDialog()
        dlg.show()
        sys.exit(app.exec())

    # 4. Запускаем главное окно
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
