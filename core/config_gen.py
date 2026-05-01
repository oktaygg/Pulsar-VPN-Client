# Copyright (C) 2026 Pulsar VPN Team
# This file is part of Pulsar VPN.
# Licensed under the GNU General Public License v3.0
# See LICENSE file in the project root for details.

import json
import os
import sys as _sys
from typing import Any, Optional


# ══════════════════════════════════════════════════════════
#  ТРАНСПОРТНЫЙ БЛОК (общий для всех протоколов)
# ══════════════════════════════════════════════════════════

def _build_transport(s_info: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Строит блок transport для sing-box на основе типа транспорта."""
    t = s_info.get('transport', 'tcp')

    if t == 'ws':
        block: dict[str, Any] = {"type": "ws"}
        if s_info.get('path'):
            block["path"] = s_info['path']
        if s_info.get('ws_host'):
            block["headers"] = {"Host": s_info['ws_host']}
        return block

    if t == 'grpc':
        return {"type": "grpc", "service_name": s_info.get('serviceName', '')}

    if t == 'http':
        block: dict[str, Any] = {"type": "http"}
        if s_info.get('path'):
            block["path"] = s_info['path']
        if s_info.get('ws_host'):
            block["host"] = [s_info['ws_host']]
        return block

    return None


def _build_tls(s_info: dict[str, Any], reality: bool = False) -> Optional[dict[str, Any]]:
    """Строит блок tls для sing-box."""
    security = s_info.get('security', '')
    if not security or security == 'none':
        return None

    tls: dict[str, Any] = {
        "enabled": True,
        "server_name": s_info.get('sni') or s_info.get('host', ''),
    }

    fp = s_info.get('fp', 'chrome')
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}

    if reality and s_info.get('pbk'):
        tls["reality"] = {
            "enabled": True,
            "public_key": s_info['pbk'],
            "short_id": s_info.get('sid', ''),
        }

    return tls


# ══════════════════════════════════════════════════════════
#  OUTBOUND-СТРОИТЕЛИ ПО ПРОТОКОЛАМ
# ══════════════════════════════════════════════════════════

def _build_vless_outbound(s_info: dict[str, Any]) -> dict[str, Any]:
    security = s_info.get('security', 'reality')
    is_reality = security == 'reality'

    outbound: dict[str, Any] = {
        "type": "vless",
        "tag": "proxy",
        "server": s_info['host'],
        "server_port": int(s_info['port']),
        "uuid": s_info['uuid'],
        "packet_encoding": "xudp",
    }

    flow = s_info.get('flow', '')
    if flow:
        outbound["flow"] = flow

    tls = _build_tls(s_info, reality=is_reality)
    if tls:
        outbound["tls"] = tls

    transport = _build_transport(s_info)
    if transport:
        outbound["transport"] = transport

    return outbound


def _build_vmess_outbound(s_info: dict[str, Any]) -> dict[str, Any]:
    security = s_info.get('security', '')

    outbound: dict[str, Any] = {
        "type": "vmess",
        "tag": "proxy",
        "server": s_info['host'],
        "server_port": int(s_info['port']),
        "uuid": s_info['uuid'],
        "alter_id": int(s_info.get('alter_id', 0)),
        "security": "auto",
    }

    if security == 'tls':
        tls = _build_tls(s_info, reality=False)
        if tls:
            outbound["tls"] = tls

    transport = _build_transport(s_info)
    if transport:
        outbound["transport"] = transport

    return outbound


def _build_trojan_outbound(s_info: dict[str, Any]) -> dict[str, Any]:
    outbound: dict[str, Any] = {
        "type": "trojan",
        "tag": "proxy",
        "server": s_info['host'],
        "server_port": int(s_info['port']),
        "password": s_info['password'],
    }

    tls = _build_tls(s_info, reality=False)
    if tls:
        outbound["tls"] = tls

    transport = _build_transport(s_info)
    if transport:
        outbound["transport"] = transport

    return outbound


def _build_shadowsocks_outbound(s_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": s_info['host'],
        "server_port": int(s_info['port']),
        "method": s_info.get('method', 'aes-256-gcm'),
        "password": s_info['password'],
    }


# ══════════════════════════════════════════════════════════
#  ГЛАВНАЯ ФУНКЦИЯ ГЕНЕРАЦИИ КОНФИГА
# ══════════════════════════════════════════════════════════

_OUTBOUND_BUILDERS = {
    'vless':       _build_vless_outbound,
    'vmess':       _build_vmess_outbound,
    'trojan':      _build_trojan_outbound,
    'shadowsocks': _build_shadowsocks_outbound,
}


def generate_sing_box_config(
    s_info: dict[str, Any],
    app_whitelist: Optional[list[str]] = None,
) -> dict[str, Any]:
    protocol = s_info.get('protocol', 'vless')
    original_host = s_info['host']

    builder = _OUTBOUND_BUILDERS.get(protocol, _build_vless_outbound)
    proxy_outbound = builder(s_info)

    # ── TUN inbound ───────────────────────────────────────
    # Основной интерфейс — перехватывает весь трафик системы
    # stack: "mixed" = лучшая совместимость на Windows
    # sniff: True = автоопределение протоколов
    tun_inbound: dict[str, Any] = {
        "type": "tun",
        "tag": "tun-in",
        "interface_name": "sing-box",
        "address": "172.19.0.1/30",  # только IPv4
        "mtu": 9000,
        "auto_route": True,
        "strict_route": True,
        "stack": "system",  # system вместо mixed для лучшей совместимости
        "sniff": True,
    }

    # ── Маршрутные правила ────────────────────────────────
    route_rules: list[dict[str, Any]] = []

    # Правило 1: Локальные IP-адреса всегда напрямую
    route_rules.append({
        "ip_is_private": True,
        "outbound": "direct"
    })

    # Правило 2: Белый список приложений
    if app_whitelist:
        for app in app_whitelist:
            route_rules.append({
                "process_name": [app],
                "outbound": "proxy"
            })
        final_outbound = "direct"
    else:
        final_outbound = "proxy"

    # ── Полные правила маршрутизации ──────────────────────
    route_rules_full: list[dict[str, Any]] = [
                                                 {"action": "sniff"},
                                                 {"protocol": "dns", "action": "hijack-dns"},
                                             ] + route_rules

    # ── DNS блок ─────────────────────────────────────────
    dns_block: dict[str, Any] = {
        "servers": [
            {
                "tag": "dns-remote",
                "address": "udp://8.8.8.8",
                "detour": "proxy",
            },
            {
                "tag": "dns-direct",
                "address": "udp://8.8.4.4",
                "detour": "direct",
            },
        ],
        "rules": [
            {
                "domain_suffix": [original_host],
                "server": "dns-direct"
            },
            {
                "domain_suffix": [
                    "local", "localhost", "lan", "home", "internal"
                ],
                "server": "dns-direct"
            },
        ],
        "final": "dns-remote",
        "independent_cache": True,
        "strategy": "ipv4_only",
    }

    # ── Сборка полного конфига ────────────────────────────
    config: dict[str, Any] = {
        "log": {
            "level": "info",
            "timestamp": True
        },
        "dns": dns_block,
        "inbounds": [tun_inbound],
        "outbounds": [
            proxy_outbound,
            {"type": "direct", "tag": "direct"},
            # bypass НЕ НУЖЕН — strict_route: False сам всё сделает
        ],
        "route": {
            "auto_detect_interface": True,
            "rules": route_rules_full,
            "final": final_outbound,
        },
    }

    return config


# ══════════════════════════════════════════════════════════
#  XRAY КОНФИГ — для xhttp / splithttp серверов
# ══════════════════════════════════════════════════════════

def generate_xray_config(
        s_info: dict[str, Any],
        app_whitelist: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Генерирует конфиг Xray (TUN-режим) для серверов с xhttp/splithttp.
    Архитектура:
      - TUN inbound → freedom (direct) для системного трафика
      - SOCKS inbound → XHTTP outbound для приложений из белого списка
      - Или наоборот: всё в XHTTP, кроме системного
    """
    protocol = s_info.get('protocol', 'vless')
    transport = s_info.get('transport', 'xhttp')
    host = s_info['host']
    port = int(s_info['port'])

    # ── Собираем streamSettings ────────────────────────────
    stream_settings: dict[str, Any] = {
        "network": transport,
        "security": s_info.get('security', 'tls'),
    }

    # TLS настройки
    if s_info.get('security') in ('tls', 'reality'):
        tls_settings: dict[str, Any] = {
            "serverName": s_info.get('sni') or s_info.get('host', ''),
        }
        fp = s_info.get('fp', 'chrome')
        if fp:
            tls_settings["fingerprint"] = fp

        if s_info.get('security') == 'reality' and s_info.get('pbk'):
            tls_settings["publicKey"] = s_info['pbk']
            tls_settings["shortId"] = s_info.get('sid', '')
            tls_settings["serverName"] = s_info.get('sni', '')

        stream_settings["tlsSettings"] = tls_settings

    # Транспортные настройки
    if transport == 'xhttp':
        stream_settings["xhttpSettings"] = {
            "path": s_info.get('path', '/'),
            "host": s_info.get('ws_host', ''),
        }
        if s_info.get('mode'):
            stream_settings["xhttpSettings"]["mode"] = s_info['mode']
    elif transport == 'splithttp':
        stream_settings["splithttpSettings"] = {
            "path": s_info.get('path', '/'),
            "host": s_info.get('ws_host', ''),
        }
    elif transport == 'ws':
        stream_settings["wsSettings"] = {
            "path": s_info.get('path', '/'),
        }
        if s_info.get('ws_host'):
            stream_settings["wsSettings"]["headers"] = {
                "Host": s_info['ws_host']
            }

    # ── Строим outbound ────────────────────────────────────
    outbound: dict[str, Any] = {
        "protocol": protocol,
        "tag": "proxy",
        "settings": {},
    }

    if protocol == 'vless':
        outbound["settings"]["vnext"] = [{
            "address": host,
            "port": port,
            "users": [{
                "id": s_info['uuid'],
                "encryption": "none",
            }],
        }]
        flow = s_info.get('flow', '')
        if flow:
            outbound["settings"]["vnext"][0]["users"][0]["flow"] = flow

    elif protocol == 'vmess':
        outbound["settings"]["vnext"] = [{
            "address": host,
            "port": port,
            "users": [{
                "id": s_info['uuid'],
                "alterId": int(s_info.get('alter_id', 0)),
                "security": "auto",
            }],
        }]

    elif protocol == 'trojan':
        outbound["settings"]["servers"] = [{
            "address": host,
            "port": port,
            "password": s_info['password'],
        }]

    outbound["streamSettings"] = stream_settings

    # ── TUN inbound ───────────────────────────────────────
    tun_inbound: dict[str, Any] = {
        "tag": "tun-in",
        "protocol": "tun",
        "settings": {
            "name": "tun0",
            "mtu": 9000,
            "ipv4": "172.19.0.1/30",
            "ipv6": None,
        },
        "sniffing": {
            "enabled": True,
            "destOverride": ["http", "tls"],
        },
    }

    # ── Routing ───────────────────────────────────────────
    routing_rules: list[dict[str, Any]] = [
        {
            # Локальные адреса — напрямую
            "type": "field",
            "ip": ["geoip:private"],
            "outboundTag": "direct",
        },
    ]

    if app_whitelist:
        # Белый список: только указанные приложения через proxy
        for app in app_whitelist:
            routing_rules.append({
                "type": "field",
                "domain": [f"fullname:{app}"],
                "outboundTag": "proxy",
            })
        # Всё остальное — напрямую
        routing_rules.append({
            "type": "field",
            "network": "tcp,udp",
            "outboundTag": "direct",
        })
    else:
        # Без белого списка — всё через proxy
        routing_rules.append({
            "type": "field",
            "network": "tcp,udp",
            "outboundTag": "proxy",
        })

    # ── Сборка конфига ────────────────────────────────────
    config: dict[str, Any] = {
        "log": {
            "loglevel": "info",
        },
        "inbounds": [tun_inbound],
        "outbounds": [
            outbound,
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": routing_rules,
        },
    }

    return config


# ══════════════════════════════════════════════════════════
#  СОХРАНЕНИЕ КОНФИГА НА ДИСК
# ══════════════════════════════════════════════════════════

def _get_base_dir():
    """
    Папка для записи config.json.
    """
    if getattr(_sys, 'frozen', False):
        return os.path.dirname(_sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save_xray_config(config_dict: dict) -> None:
    """
    Сохраняет конфигурацию в bin/xray/xray_config.json для Xray.
    """
    base = _get_base_dir()
    xray_dir = os.path.join(base, "bin", "xray")
    os.makedirs(xray_dir, exist_ok=True)
    target_path = os.path.join(xray_dir, "xray_config.json")

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=4)


def save_config(config_dict: dict) -> None:
    """
    Сохраняет конфигурацию в bin/config.json для sing-box.
    """
    base = _get_base_dir()
    bin_dir = os.path.join(base, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    target_path = os.path.join(bin_dir, "config.json")

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=4)