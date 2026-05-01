# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

import base64
import hashlib
import json
import logging
import platform
import socket
import time
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

import requests

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ══════════════════════════════════════════════════════════

def measure_ping(host: str, port: int, timeout: float = 2.0) -> str:
    """Измеряет задержку TCP-соединения до хоста.

    Returns:
        Строка вида '42ms' или '—' если хост недоступен.
    """
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        ms = (time.time() - start) * 1000
        return f"{ms:.0f}ms"
    except OSError:
        return "—"


def get_flag_emoji(country_code: str) -> str:
    """Конвертирует двухбуквенный код страны (ISO 3166-1) в эмодзи-флаг."""
    if not country_code or len(country_code) != 2:
        return "🌐"
    code = country_code.upper()
    try:
        return (
            chr(0x1F1E6 + ord(code[0]) - ord('A')) +
            chr(0x1F1E6 + ord(code[1]) - ord('A'))
        )
    except (ValueError, TypeError):
        return "🌐"


def format_bytes(b: float) -> str:
    """Форматирует количество байт в читаемую строку (Б, КБ, МБ, ГБ, ТБ)."""
    for unit in ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ']:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} ТБ"


def _normalize_transport(raw: str) -> str:
    """Приводит название транспорта к внутреннему формату sing-box."""
    raw = raw.lower()
    if raw in ('gun', 'grpc'):
        return 'grpc'
    if raw in ('h2', 'http'):
        return 'http'
    return raw  # tcp, ws, quic и др.


def _normalize_fp(raw: str) -> str:
    """Проверяет fingerprint браузера и возвращает 'chrome' если значение неизвестно."""
    valid = {'chrome', 'firefox', 'safari', 'ios', 'android', 'edge', '360', 'randomized'}
    return raw if raw in valid else 'chrome'


# ══════════════════════════════════════════════════════════
#  ЗАГРУЗКА ПОДПИСКИ
# ══════════════════════════════════════════════════════════

KNOWN_SCHEMES = (
    'vless://', 'vmess://', 'trojan://', 'ss://', 'ssr://',
    'hysteria://', 'hysteria2://', 'tuic://',
)


def _is_plain_links(text: str) -> bool:
    """Проверяет, является ли текст списком обычных прокси-ссылок (не Base64 и не JSON)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and any(lines[0].startswith(s) for s in KNOWN_SCHEMES)


def _extract_from_json_config(data: dict | list) -> list[str]:
    """Извлекает серверные ссылки из JSON-конфига формата V2Ray/Xray/sing-box.

    Returns:
        Список строк вида protocol://...
    """
    result: list[str] = []
    configs = data if isinstance(data, list) else [data]

    for config in configs:
        outbounds = config.get('outbounds', [])
        for out in outbounds:
            protocol = out.get('protocol') or out.get('type', '')

            # ── VLESS / VMess (структура с vnext) ──────────────────────
            if protocol in ('vless', 'vmess'):
                settings = out.get('settings', {})
                for vnext in settings.get('vnext', []):
                    host = vnext.get('address', '')
                    port = vnext.get('port', 443)
                    tag  = out.get('tag', protocol.upper())
                    for user in vnext.get('users', [{}]):
                        uid = user.get('id', '')
                        aid = user.get('alterId', 0)
                        # Параметры транспортного уровня
                        ss        = out.get('streamSettings', {})
                        net       = ss.get('network', 'tcp')
                        security  = ss.get('security', '')
                        tls_cfg   = ss.get('tlsSettings', ss.get('realitySettings', {}))
                        sni       = tls_cfg.get('serverName', '')
                        pbk       = tls_cfg.get('publicKey', '')
                        sid       = tls_cfg.get('shortId', '')
                        fp        = tls_cfg.get('fingerprint', 'chrome')
                        ws_cfg    = ss.get('wsSettings', {})
                        path      = ws_cfg.get('path', '/')
                        ws_host   = ws_cfg.get('headers', {}).get('Host', '')
                        grpc_sn   = ss.get('grpcSettings', {}).get('serviceName', '')

                        if protocol == 'vmess':
                            # VMess кодируем в base64-json
                            vmess_obj = {
                                'v': '2', 'ps': tag, 'add': host, 'port': port,
                                'id': uid, 'aid': aid, 'net': net,
                                'tls': security, 'sni': sni, 'fp': fp,
                                'path': path, 'host': ws_host,
                            }
                            b64 = base64.b64encode(json.dumps(vmess_obj).encode()).decode()
                            result.append(f"vmess://{b64}")
                        else:
                            # VLESS URI
                            uri_params = f"type={net}&security={security}"
                            if sni:                  uri_params += f"&sni={sni}"
                            if pbk:                  uri_params += f"&pbk={pbk}"
                            if sid:                  uri_params += f"&sid={sid}"
                            if fp:                   uri_params += f"&fp={fp}"
                            if path and net == 'ws': uri_params += f"&path={path}"
                            if ws_host:              uri_params += f"&host={ws_host}"
                            if grpc_sn:              uri_params += f"&serviceName={grpc_sn}"
                            result.append(f"vless://{uid}@{host}:{port}?{uri_params}#{tag}")

            # ── Trojan ─────────────────────────────────────────────────
            elif protocol == 'trojan':
                settings = out.get('settings', {})
                for trojan_server in settings.get('servers', []):
                    host     = trojan_server.get('address', '')
                    port     = trojan_server.get('port', 443)
                    password = trojan_server.get('password', '')
                    tag      = out.get('tag', 'Trojan')
                    ss       = out.get('streamSettings', {})
                    sni      = ss.get('tlsSettings', {}).get('serverName', host)
                    result.append(f"trojan://{password}@{host}:{port}?sni={sni}#{tag}")

            # ── Shadowsocks ────────────────────────────────────────────
            elif protocol in ('shadowsocks', 'ss'):
                settings = out.get('settings', {})
                for ss_server in settings.get('servers', []):
                    host     = ss_server.get('address', '')
                    port     = ss_server.get('port', 8388)
                    method   = ss_server.get('method', 'aes-256-gcm')
                    password = ss_server.get('password', '')
                    tag      = out.get('tag', 'SS')
                    encoded  = base64.b64encode(f"{method}:{password}".encode()).decode()
                    result.append(f"ss://{encoded}@{host}:{port}#{tag}")

    return result


def _decode_subscription(content: str) -> list[str]:
    """Автоматически определяет формат подписки и возвращает список ссылок.

    Поддерживает: plain-text, Base64, JSON (V2Ray/Xray/sing-box).
    """
    stripped = content.strip()

    # 1. JSON-конфиг
    if stripped.startswith('{') or stripped.startswith('['):
        try:
            data = json.loads(stripped)
            extracted = _extract_from_json_config(data)
            if extracted:
                return extracted
        except (json.JSONDecodeError, AttributeError):
            pass

    # 2. Уже plain-text ссылки
    if _is_plain_links(stripped):
        return [line.strip() for line in stripped.splitlines() if line.strip()]

    # 3. Base64 — декодируем и повторяем попытку
    b64 = stripped.replace('-', '+').replace('_', '/')
    missing = len(b64) % 4
    if missing:
        b64 += '=' * (4 - missing)
    try:
        decoded = base64.b64decode(b64.encode('ascii', 'ignore')).decode('utf-8')
        decoded_stripped = decoded.strip()
        if decoded_stripped.startswith('{') or decoded_stripped.startswith('['):
            try:
                data = json.loads(decoded_stripped)
                extracted = _extract_from_json_config(data)
                if extracted:
                    return extracted
            except (json.JSONDecodeError, AttributeError):
                pass
        lines = [line.strip() for line in decoded.replace('\r\n', '\n').split('\n') if line.strip()]
        if lines:
            return lines
    except (ValueError, UnicodeDecodeError):
        pass

    # 4. Фолбэк — возвращаем как есть
    return [line.strip() for line in stripped.splitlines() if line.strip()]


def _get_hwid() -> str:
    """Возвращает уникальный идентификатор устройства (MD5 от имени хоста + архитектуры)."""
    raw = platform.node() + platform.machine()
    return hashlib.md5(raw.encode()).hexdigest().upper()


def _is_stub_response(links: list[str]) -> bool:
    """Проверяет, является ли ответ сервера заглушкой (App not supported)."""
    if len(links) != 1:
        return False
    link = links[0].lower()
    stub_signs = ['0.0.0.0', '00000000-0000-0000-0000-000000000000', 'not supported']
    return any(sign in link for sign in stub_signs)


def fetch_subscription(url: str) -> tuple[list[str], Optional[dict[str, Any]]]:
    """Загружает подписку и возвращает список ссылок и информацию об аккаунте.

    Автоматически перебирает User-Agent, чтобы работать и с HWID-серверами
    (panthera/renawave), и с обычными (ultm.in).

    Returns:
        Кортеж (список ссылок, словарь userinfo) или ([], None) при ошибке.
    """
    candidates = [
        # Hiddify с HWID — для серверов типа renawave/panthera
        {
            'User-Agent': 'Hiddify/2.0.5 (com.hiddify.app; build:352; Android 14)',
            'X-Hwid': _get_hwid(),
            'Accept': '*/*',
        },
        # NekoBox — для большинства подписок
        {
            'User-Agent': 'NekoBox/1.3.1',
            'Accept': '*/*',
        },
        # Запасной вариант
        {
            'User-Agent': 'clash-meta',
            'Accept': '*/*',
        },
    ]

    last_error: Optional[Exception] = None
    for headers in candidates:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()

            account_info = parse_subscription_userinfo(response.headers)
            fetched_links = _decode_subscription(response.text)

            if _is_stub_response(fetched_links):
                continue
            if not fetched_links:
                continue

            return fetched_links, account_info

        except requests.RequestException as e:
            last_error = e
            continue

    if last_error:
        logger.error("Ошибка загрузки подписки: %s", last_error)
    else:
        logger.warning("Подписка пустая или формат не распознан")
    return [], None


def parse_subscription_userinfo(headers: Any) -> Optional[dict[str, Any]]:
    """Парсит заголовок Subscription-Userinfo и возвращает данные об аккаунте.

    Returns:
        Словарь с ключами title, upload, download, total, expire или None.
    """
    raw = headers.get('subscription-userinfo') or headers.get('Subscription-Userinfo')

    # Название сервиса (может быть закодировано в base64)
    title_raw = (
        headers.get('profile-title') or
        headers.get('Profile-Title') or ''
    )
    title = ''
    if title_raw:
        if title_raw.startswith('base64:'):
            title_raw = title_raw[7:]
        try:
            missing = len(title_raw) % 4
            title = base64.b64decode(title_raw + '=' * missing).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            title = title_raw  # не base64 — оставляем как есть

    if not raw:
        return {'title': title} if title else None

    parsed_info: dict[str, str] = {}
    for part in raw.split(';'):
        part = part.strip()
        if '=' in part:
            k, _, v = part.partition('=')
            parsed_info[k.strip()] = v.strip()
    try:
        return {
            'title':    title,
            'upload':   int(parsed_info.get('upload', 0)),
            'download': int(parsed_info.get('download', 0)),
            'total':    int(parsed_info.get('total', 0)),
            'expire':   int(parsed_info.get('expire', 0)),
        }
    except (ValueError, TypeError):
        return {'title': title} if title else None


# ══════════════════════════════════════════════════════════
#  ПАРСЕРЫ ПРОТОКОЛОВ
# ══════════════════════════════════════════════════════════

def parse_vless_link(link: str) -> Optional[dict[str, Any]]:
    """Парсит ссылку формата vless://uuid@host:port?params#tag.

    Returns:
        Словарь с параметрами сервера или None при ошибке.
    """
    try:
        parsed    = urlparse(link)
        params    = parse_qs(parsed.query)
        transport = _normalize_transport(params.get('type', ['tcp'])[0])
        security  = params.get('security', ['reality'])[0]
        server_info = {
            "protocol":    "vless",
            "uuid":        parsed.username or '',
            "host":        parsed.hostname or '',
            "port":        parsed.port or 443,
            "sni":         params.get('sni', [''])[0],
            "pbk":         params.get('pbk', [''])[0],
            "sid":         params.get('sid', [''])[0],
            "fp":          _normalize_fp(params.get('fp', ['chrome'])[0]),
            "security":    security,
            "transport":   transport,
            "path":        params.get('path', ['/'])[0],
            "ws_host":     params.get('host', [''])[0],
            "serviceName": params.get('serviceName', [''])[0],
            "tag":         unquote(parsed.fragment) if parsed.fragment else "VLESS Server",
            "password": "", "method": "", "alter_id": 0,
            "flow": params.get('flow', [''])[0],
        }
        if not server_info['sni']:
            server_info['sni'] = server_info['host']
        return server_info
    except (ValueError, AttributeError) as e:
        logger.error("[VLESS] Ошибка парсинга: %s", e)
        return None


def parse_vmess_link(link: str) -> Optional[dict[str, Any]]:
    """Парсит ссылку формата vmess://<base64json>.

    Returns:
        Словарь с параметрами сервера или None при ошибке.
    """
    try:
        b64 = link[8:]
        missing = len(b64) % 4
        if missing:
            b64 += '=' * (4 - missing)
        data      = json.loads(base64.b64decode(b64).decode('utf-8'))
        transport = _normalize_transport(data.get('net', 'tcp'))
        security  = data.get('tls', '')
        server_info = {
            "protocol":    "vmess",
            "uuid":        data.get('id', ''),
            "host":        data.get('add', ''),
            "port":        int(data.get('port', 443)),
            "alter_id":    int(data.get('aid', 0)),
            "security":    security,
            "transport":   transport,
            "path":        data.get('path', '/'),
            "ws_host":     data.get('host', ''),
            "sni":         data.get('sni', '') or data.get('host', ''),
            "fp":          _normalize_fp(data.get('fp', 'chrome')),
            "serviceName": data.get('path', ''),
            "tag":         data.get('ps', 'VMess Server'),
            "pbk": "", "sid": "", "password": "", "method": "",
        }
        if not server_info['sni']:
            server_info['sni'] = server_info['host']
        return server_info
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("[VMess] Ошибка парсинга: %s", e)
        return None


def parse_trojan_link(link: str) -> Optional[dict[str, Any]]:
    """Парсит ссылку формата trojan://password@host:port?params#tag.

    Returns:
        Словарь с параметрами сервера или None при ошибке.
    """
    try:
        parsed    = urlparse(link)
        params    = parse_qs(parsed.query)
        transport = _normalize_transport(params.get('type', ['tcp'])[0])
        security  = params.get('security', ['tls'])[0]
        server_info = {
            "protocol":    "trojan",
            "password":    parsed.username or '',
            "uuid":        '',
            "host":        parsed.hostname or '',
            "port":        parsed.port or 443,
            "sni":         params.get('sni', [''])[0],
            "fp":          _normalize_fp(params.get('fp', ['chrome'])[0]),
            "security":    security,
            "transport":   transport,
            "path":        params.get('path', ['/'])[0],
            "ws_host":     params.get('host', [''])[0],
            "serviceName": params.get('serviceName', [''])[0],
            "tag":         unquote(parsed.fragment) if parsed.fragment else "Trojan Server",
            "pbk": "", "sid": "", "alter_id": 0, "method": "",
        }
        if not server_info['sni']:
            server_info['sni'] = server_info['host']
        return server_info
    except (ValueError, AttributeError) as e:
        logger.error("[Trojan] Ошибка парсинга: %s", e)
        return None


def parse_shadowsocks_link(link: str) -> Optional[dict[str, Any]]:
    """Парсит ссылку Shadowsocks в двух форматах.

    Новый: ss://<base64(method:pass)>@host:port#tag
    Старый: ss://<base64(method:pass@host:port)>#tag

    Returns:
        Словарь с параметрами сервера или None при ошибке.
    """
    try:
        parsed = urlparse(link)
        tag = unquote(parsed.fragment) if parsed.fragment else "SS Server"

        if parsed.hostname:
            # Новый формат: userinfo — это base64(method:password)
            raw_userinfo = parsed.username or ''
            try:
                missing = len(raw_userinfo) % 4
                decoded_user = base64.b64decode(raw_userinfo + '=' * missing).decode('utf-8')
            except (ValueError, UnicodeDecodeError):
                decoded_user = unquote(raw_userinfo)

            if ':' in decoded_user:
                method, password = decoded_user.split(':', 1)
            else:
                method, password = 'aes-256-gcm', decoded_user

            return {
                "protocol": "shadowsocks",
                "method":   method,
                "password": password,
                "host":     parsed.hostname,
                "port":     parsed.port or 8388,
                "tag":      tag,
                "uuid": "", "sni": "", "pbk": "", "sid": "",
                "fp": "chrome", "security": "", "transport": "tcp",
                "path": "/", "ws_host": "", "serviceName": "", "alter_id": 0,
            }

        # Старый формат: весь блок закодирован целиком
        b64_part = link[5:].split('#')[0]
        missing = len(b64_part) % 4
        decoded = base64.b64decode(b64_part + '=' * missing).decode('utf-8')
        raw_userinfo, hostinfo = decoded.rsplit('@', 1)
        method, password = raw_userinfo.split(':', 1)
        host, port_str = hostinfo.rsplit(':', 1)

        return {
            "protocol": "shadowsocks",
            "method":   method,
            "password": password,
            "host":     host,
            "port":     int(port_str),
            "tag":      tag,
            "uuid": "", "sni": "", "pbk": "", "sid": "",
            "fp": "chrome", "security": "", "transport": "tcp",
            "path": "/", "ws_host": "", "serviceName": "", "alter_id": 0,
        }

    except (ValueError, UnicodeDecodeError) as e:
        logger.error("[Shadowsocks] Ошибка парсинга: %s", e)
        return None


# ══════════════════════════════════════════════════════════
#  УНИВЕРСАЛЬНЫЙ РОУТЕР
# ══════════════════════════════════════════════════════════

def parse_any_link(link: str) -> Optional[dict[str, Any]]:
    """Определяет протокол по схеме ссылки и вызывает нужный парсер.

    Returns:
        Словарь с параметрами сервера или None, если ссылка битая/неизвестная.
    """
    link = link.strip()
    if link.startswith('vless://'):
        return parse_vless_link(link)
    if link.startswith('vmess://'):
        return parse_vmess_link(link)
    if link.startswith('trojan://'):
        return parse_trojan_link(link)
    if link.startswith('ss://'):
        return parse_shadowsocks_link(link)
    return None


# ══════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ
# ══════════════════════════════════════════════════════════

def parse_server_info(config_line: str) -> Optional[str]:
    """Возвращает читаемую строку с описанием сервера из ссылки."""
    try:
        parsed = urlparse(config_line)
        name = unquote(parsed.fragment) if parsed.fragment else "Без названия"
        return f"✅ {name} [{parsed.scheme.upper()}] -> {parsed.hostname}"
    except (ValueError, AttributeError):
        return None