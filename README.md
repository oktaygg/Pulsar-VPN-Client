<p align="center">
  <img src="assets/app_images/icon.ico" width="64">
</p>

<h1 align="center">Pulsar</h1>

<p align="center">
  Современный VPN-клиент для Windows на базе sing-box<br>
  <sub>GPL-3.0 • PyQt6 • Открытый исходный код</sub>
</p>

---

## ✨ Что умеет

- **Все основные протоколы** — VLESS (Reality), VMess, Trojan, Shadowsocks
- **Подписки по ссылке** — вставил URL и готово
- **Белые списки** — выбирай какие приложения ходят через VPN
- **Мгновенный пинг** — замер задержки до всех серверов при загрузке
- **Кастомизация** — цвет темы, фоновое изображение
- **Системный трей** — сворачивается, не мешает

## 📥 Установка

Скачай установщик со страницы [релизов](https://github.com/korwinouir/pulsar/releases) и запусти.

> Требуются права администратора (нужны для TUN-интерфейса).

## ⚙️ Быстрый старт

1. Запусти Pulsar от имени администратора
2. Нажми **+** и вставь ссылку на твою подписку
3. Выбери сервер из списка
4. Нажми кнопку питания

Готово.


📁 Устройство проекта

pulsar/
├── main.py                 # Точка входа
├── core/
│   ├── parser.py           # Парсинг VPN-ссылок и подписок
│   ├── config_gen.py       # Генерация конфига sing-box
│   └── runner.py           # Запуск и остановка sing-box
├── ui/
│   ├── main_window.py      # Главное окно (+ трей, тайтлбар)
│   ├── servers_page.py     # Страница серверов
│   ├── settings_page.py    # Настройки темы и фона
│   ├── whitelist_page.py   # Белые списки приложений
│   ├── info_page.py        # Информация о версии
│   ├── theme.py            # Менеджер тем и стилей
│   ├── config.py           # Хранилище настроек
│   └── widgets.py          # Общие виджеты
├── bin/
│   └── sing-box.exe        # Ядро туннеля
└── assets/
    ├── app_images/         # Иконки, фон
    ├── countries/          # Флаги стран
    └── wl_images/          # Иконки приложений

 
📜 Лицензия
Pulsar — свободное программное обеспечение под лицензией GNU GPL v3.0.

Ядро sing-box © nekohasekai, также GPL-3.0.

## License
This project is licensed under the [GNU General Public License v3.0](LICENSE).