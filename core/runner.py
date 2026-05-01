# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
core/runner.py — управление процессом sing-box.

Особенности:
  - Автоматически находит sing-box.exe
  - Очищает зависшие процессы и TUN-адаптеры перед запуском
  - Поддерживает корректную остановку через taskkill
"""

import os
import sys
import subprocess
import time
import logging

logger = logging.getLogger(__name__)


def _get_base_path() -> str:
    """
    Путь к папке где лежат bin/, assets/ и т.д.
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        internal = os.path.join(exe_dir, '_internal')
        if os.path.isdir(internal):
            return internal
        return exe_dir

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_config_dir() -> str:
    """
    Папка для записи config.json (нужны права на запись).
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class VPNRunner:
    """Управляет жизненным циклом процесса sing-box."""

    def __init__(self, executable_path='bin/sing-box.exe', config_path='config.json'):
        self.exe = os.path.join(_get_base_path(), executable_path)
        self.config = os.path.join(_get_config_dir(), 'bin', config_path)
        self.process = None

    @staticmethod
    def cleanup_network():
        """
        Убивает застрявший sing-box и удаляет TUN-адаптер.
        """
        # Убиваем любой висящий sing-box.exe
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'sing-box.exe'],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        # Удаляем старый TUN-адаптер
        try:
            subprocess.run(
                [
                    'powershell', '-Command',
                    'Get-NetAdapter -Name "sing-box" -ErrorAction SilentlyContinue'
                    ' | Remove-NetAdapter -Confirm:$false',
                ],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def start(self):
        """Запускает sing-box с TUN-конфигом."""
        if self.process:
            logger.warning("sing-box уже запущен")
            return

        if not os.path.isfile(self.exe):
            logger.error('sing-box.exe не найден: %s', self.exe)
            return

        if not os.path.isfile(self.config):
            logger.error('config.json не найден: %s', self.config)
            return

        # Очистка перед запуском
        self.cleanup_network()

        env = os.environ.copy()
        env['ENABLE_DEPRECATED_LEGACY_DNS_SERVERS'] = 'true'

        # Лог sing-box для отладки
        _log_path = os.path.join(os.path.dirname(self.config), 'singbox.log')
        try:
            os.makedirs(os.path.dirname(self.config), exist_ok=True)
            _log_file = open(_log_path, 'w', encoding='utf-8')
        except OSError:
            _log_file = subprocess.DEVNULL

        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

            self.process = subprocess.Popen(
                [self.exe, 'run', '-c', self.config],
                cwd=os.path.dirname(self.exe),
                env=env,
                creationflags=creationflags,
                stdout=_log_file,
                stderr=_log_file,
            )

            # Даём время на инициализацию TUN-адаптера
            time.sleep(1)

            # Проверяем, не упал ли сразу
            if self.process.poll() is not None:
                logger.error(
                    'sing-box завершился с кодом %s, проверьте %s',
                    self.process.poll(),
                    _log_path
                )
                self.process = None

        except OSError as e:
            logger.error('Ошибка запуска sing-box: %s', e)
            self.process = None
        finally:
            if hasattr(_log_file, 'close'):
                _log_file.close()

    def is_running(self) -> bool:
        """Проверяет, работает ли процесс sing-box."""
        return self.process is not None and self.process.poll() is None

    def stop(self):
        """
        Останавливает sing-box.
        Использует taskkill /F /T чтобы убить и основой процесс и дочерние.
        После остановки очищает TUN-адаптер.
        """
        if not self.process:
            return

        try:
            # /T — убивает дерево процессов
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(self.process.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            # Если за 8 секунд не убился — повторяем без таймаута
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(self.process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                pass
        except OSError:
            pass
        finally:
            self.process = None
            time.sleep(0.3)
            self.cleanup_network()

class XrayRunner:
    """Управляет жизненным циклом процесса Xray (для xhttp/splithttp)."""

    def __init__(self, executable_path='bin/xray/xray.exe', config_path='xray_config.json'):
        self.exe = os.path.join(_get_base_path(), executable_path)
        self.config = os.path.join(_get_config_dir(), 'bin', 'xray', config_path)
        self.process = None

    @staticmethod
    def cleanup_network():
        """
        Убивает застрявший xray и удаляет TUN-адаптер.
        """
        try:
            subprocess.run(
                ['taskkill', '/F', '/IM', 'xray.exe'],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

        # Xray создаёт адаптер с именем tun0
        try:
            subprocess.run(
                [
                    'powershell', '-Command',
                    'Get-NetAdapter -Name "tun0" -ErrorAction SilentlyContinue'
                    ' | Remove-NetAdapter -Confirm:$false',
                ],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def start(self):
        """Запускает Xray с TUN-конфигом."""
        if self.process:
            logger.warning("Xray уже запущен")
            return

        if not os.path.isfile(self.exe):
            logger.error('xray.exe не найден: %s', self.exe)
            return

        if not os.path.isfile(self.config):
            logger.error('xray_config.json не найден: %s', self.config)
            return

        self.cleanup_network()

        xray_dir = os.path.dirname(self.exe)
        log_path = os.path.join(xray_dir, 'xray.log')

        try:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

            with open(log_path, 'w', encoding='utf-8') as log_file:
                self.process = subprocess.Popen(
                    [self.exe, 'run', '-c', self.config],
                    cwd=xray_dir,  # важно: wintun.dll, geoip.dat ищутся в cwd
                    creationflags=creationflags,
                    stdout=log_file,
                    stderr=log_file,
                )

            time.sleep(1.5)

            if self.process.poll() is not None:
                logger.error(
                    'Xray завершился с кодом %s, проверьте %s',
                    self.process.poll(),
                    log_path,
                )
                self.process = None

        except OSError as e:
            logger.error('Ошибка запуска Xray: %s', e)
            self.process = None

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if not self.process:
            return

        try:
            subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(self.process.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8,
            )
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(self.process.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except OSError:
                pass
        except OSError:
            pass
        finally:
            self.process = None
            time.sleep(0.3)
            self.cleanup_network()