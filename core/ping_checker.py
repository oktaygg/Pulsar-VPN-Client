# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

"""
core/ping_checker.py — корректное измерение пинга до VPN-серверов.

Использует несколько методов:
  1. TCP ping — подключение к порту сервера (самый надёжный для VPN)
  2. HTTP ping — HEAD запрос (если сервер поддерживает HTTP)
  3. Fallback на ICMP только если TCP недоступен

Особенности:
  - Асинхронное измерение множества серверов
  - Корректная обработка таймаутов
  - Retry логика для нестабильных соединений
"""

import socket
import time
import asyncio
import logging
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class PingChecker:
    """
    Измеритель пинга для VPN-серверов.
    
    Использует TCP-подключение к порту сервера как основной метод,
    т.к. ICMP ping часто блокируется файрволами.
    """

    def __init__(self, timeout: float = 3.0, retries: int = 2):
        """
        Args:
            timeout: Максимальное время ожидания ответа в секундах
            retries: Количество повторных попыток при неудаче
        """
        self.timeout = timeout
        self.retries = retries
        self._executor = ThreadPoolExecutor(max_workers=10)

    def tcp_ping(self, host: str, port: int) -> Optional[int]:
        """
        TCP ping с усреднением по нескольким попыткам и отсечением аномалий.

        Измеряет пинг 3 раза и берёт медиану (среднее значение),
        чтобы исключить случайные выбросы из-за загруженности сети.

        Args:
            host: IP-адрес или домен сервера
            port: Порт сервера

        Returns:
            Пинг в миллисекундах или None если недоступен
        """
        measurements = []

        for attempt in range(self.retries + 1):  # 3 попытки по умолчанию
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(self.timeout / 2)  # Уменьшаем таймаут для каждой попытки

                start = time.perf_counter()
                result = sock.connect_ex((host, port))
                end = time.perf_counter()

                if result == 0:
                    rtt_ms = int((end - start) * 1000)
                    # Принимаем только разумные значения (1-800ms)
                    if 1 <= rtt_ms <= 800:
                        measurements.append(rtt_ms)

            except socket.timeout:
                logger.debug(f"TCP ping timeout: {host}:{port} (attempt {attempt + 1})")
            except socket.gaierror:
                logger.debug(f"DNS resolution failed: {host}")
                return None  # Нет смысла повторять при ошибке DNS
            except Exception as e:
                logger.debug(f"TCP ping error {host}:{port}: {e}")
            finally:
                if sock:
                    try:
                        sock.close()
                    except:
                        pass

            # Задержка между попытками только если не последняя
            if attempt < self.retries:
                time.sleep(0.1)

        # Если есть хотя бы одно измерение
        if measurements:
            # Сортируем и берём медиану (устойчива к выбросам)
            measurements.sort()
            median_idx = len(measurements) // 2
            return measurements[median_idx]

        return None

    def icmp_ping(self, host: str) -> Optional[int]:
        """
        ICMP ping (обычный ping) — fallback метод.
        
        НЕ рекомендуется как основной, т.к. многие серверы
        не отвечают на ICMP запросы из-за настроек файрвола.
        
        Args:
            host: IP-адрес или домен
            
        Returns:
            Пинг в миллисекундах или None
        """
        import subprocess
        import platform
        
        try:
            param = '-n' if platform.system().lower() == 'windows' else '-c'
            command = ['ping', param, '1', '-w', str(int(self.timeout * 1000)), host]
            
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout + 1,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system().lower() == 'windows' else 0,
            )
            
            if result.returncode == 0:
                # Парсим вывод ping для извлечения времени
                output = result.stdout.lower()
                
                # Windows: "time=XXms" или "время=XXмс"
                # Linux: "time=XX.X ms"
                import re
                match = re.search(r'time[=<]\s*(\d+(?:\.\d+)?)\s*m?s', output, re.IGNORECASE)
                if match:
                    return int(float(match.group(1)))
            
        except subprocess.TimeoutExpired:
            logger.debug(f"ICMP ping timeout: {host}")
        except Exception as e:
            logger.debug(f"ICMP ping error {host}: {e}")
        
        return None

    def measure_server(self, host: str, port: int, use_icmp_fallback: bool = False) -> Optional[int]:
        """
        Измеряет пинг до сервера, сначала TCP, потом ICMP если разрешено.
        
        Args:
            host: Адрес сервера
            port: Порт сервера
            use_icmp_fallback: Пробовать ICMP если TCP не сработал
            
        Returns:
            Пинг в миллисекундах или None
        """
        # Сначала пробуем TCP ping (основной метод)
        ping = self.tcp_ping(host, port)
        
        # Если TCP не сработал и разрешён fallback — пробуем ICMP
        if ping is None and use_icmp_fallback:
            ping = self.icmp_ping(host)
        
        return ping

    async def measure_multiple_async(self, servers: list[tuple[str, int]]) -> dict[tuple[str, int], Optional[int]]:
        """
        Асинхронно измеряет пинг для множества серверов.
        
        Args:
            servers: Список кортежей (host, port)
            
        Returns:
            Словарь {(host, port): ping_ms}
        """
        loop = asyncio.get_event_loop()
        tasks = []
        
        for host, port in servers:
            task = loop.run_in_executor(
                self._executor,
                self.measure_server,
                host,
                port,
                False  # ICMP fallback отключён для скорости
            )
            tasks.append((host, port, task))
        
        results = {}
        for host, port, task in tasks:
            try:
                ping = await task
                results[(host, port)] = ping
            except Exception as e:
                logger.error(f"Error measuring {host}:{port}: {e}")
                results[(host, port)] = None
        
        return results

    def measure_multiple(self, servers: list[tuple[str, int]]) -> dict[tuple[str, int], Optional[int]]:
        """
        Синхронная версия для измерения пинга множества серверов.
        Работает в любом потоке, включая QThread.

        Args:
            servers: Список кортежей (host, port)

        Returns:
            Словарь {(host, port): ping_ms}
        """
        results = {}

        # Используем ThreadPoolExecutor напрямую, без asyncio
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def measure_task(host, port):
            return host, port, self.measure_server(host, port, use_icmp_fallback=False)

        max_workers = min(15, len(servers))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(measure_task, host, port): (host, port)
                for host, port in servers
            }

            for future in as_completed(futures):
                try:
                    host, port, ping = future.result()
                    results[(host, port)] = ping
                except Exception as e:
                    host, port = futures[future]
                    logger.error(f"Error measuring {host}:{port}: {e}")
                    results[(host, port)] = None

        return results

    def cleanup(self):
        """Освобождает ресурсы."""
        self._executor.shutdown(wait=False)


# ════════════════════════════════════════════════════════
#  УТИЛИТЫ ДЛЯ РАБОТЫ С ФОРМАТОМ СЕРВЕРОВ
# ════════════════════════════════════════════════════════

def format_ping(ping_ms: Optional[int]) -> str:
    """
    Форматирует пинг для отображения в UI.
    
    Args:
        ping_ms: Пинг в миллисекундах или None
        
    Returns:
        Строка для отображения ("45 ms", "234 ms", "-")
    """
    if ping_ms is None:
        return "-"
    
    # Цветовая индикация (можно использовать в UI)
    # < 50ms  — отлично (зелёный)
    # 50-150  — хорошо (жёлтый)
    # 150-300 — средне (оранжевый)
    # > 300   — плохо (красный)
    
    return f"{ping_ms} ms"


def get_ping_quality(ping_ms: Optional[int]) -> str:
    """
    Возвращает текстовую оценку качества соединения.
    
    Returns:
        "excellent", "good", "fair", "poor", "unavailable"
    """
    if ping_ms is None:
        return "unavailable"
    elif ping_ms < 50:
        return "excellent"
    elif ping_ms < 150:
        return "good"
    elif ping_ms < 300:
        return "fair"
    else:
        return "poor"


# ════════════════════════════════════════════════════════
#  ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ════════════════════════════════════════════════════════

def measure_servers_from_parsed(parsed_servers: list[tuple[str, dict]], timeout: float = 3.0) -> dict[int, Optional[int]]:
    """
    Удобная функция для измерения пинга серверов из SubscriptionLoader.
    
    Args:
        parsed_servers: Список кортежей (link, info) где info содержит host и port
        timeout: Таймаут для каждого сервера
        
    Returns:
        Словарь {index: ping_ms или None}
    """
    checker = PingChecker(timeout=timeout, retries=2)
    
    # Формируем список (host, port) с индексами
    server_tasks = [(info["host"], info["port"]) for _, info in parsed_servers]
    
    # Измеряем все серверы
    results = checker.measure_multiple(server_tasks)
    
    # Преобразуем обратно в словарь с индексами
    ping_map = {}
    for i, (host, port) in enumerate(server_tasks):
        ping_map[i] = results.get((host, port))
    
    checker.cleanup()
    return ping_map


if __name__ == "__main__":
    # Настройка логирования для теста
    logging.basicConfig(level=logging.DEBUG)
    
    # Создаём чекер
    checker = PingChecker(timeout=3.0, retries=2)
    
    # Тестовые серверы (замени на реальные)
    test_servers = [
        ("8.8.8.8", 443),           # Google DNS (должен ответить)
        ("1.1.1.1", 443),           # Cloudflare DNS
        ("example.com", 80),        # Example domain
        ("192.168.1.254", 12345),   # Несуществующий (вернёт None)
    ]
    
    print("Измеряем пинг до серверов...")
    print("-" * 50)
    
    # Измеряем все серверы разом
    results = checker.measure_multiple(test_servers)
    
    for (host, port), ping in results.items():
        quality = get_ping_quality(ping)
        ping_str = format_ping(ping)
        print(f"{host}:{port:5d} → {ping_str:>8s}  [{quality}]")
    
    print("-" * 50)
    
    # Очистка
    checker.cleanup()
