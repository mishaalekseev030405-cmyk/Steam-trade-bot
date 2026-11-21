# Установка CS2 Trade One с iPhone через SSH

## Что готово
Панель CS2 Trade One уже находится в коде GitHub. На сервере нужен один постоянно работающий процесс Docker; само наличие исходников в GitHub **не** запускает Telegram-бота.

## Установка на Ubuntu VPS
1. Открой SSH-приложение на iPhone (например, Termius) и подключись к **своему** серверу по IP, используя логин и пароль/SSH-ключ от провайдера. Не отправляй пароль в чат ChatGPT.
2. В терминале VPS выполни одну команду:

```bash
curl -fsSLo /tmp/cs2-install.sh https://raw.githubusercontent.com/mishaalekseev030405-cmyk/Steam-trade-bot/main/CS2_Trade_One/install_server.sh && bash /tmp/cs2-install.sh
```

3. Подтверди установку, затем по запросу вставь **Telegram Owner ID**, **Telegram Bot Token** и **Market.CSGO API Key**. Токен и ключ вводятся скрыто и сохраняются **только в .env на VPS**, не в GitHub.
4. Убедись, что Docker-контейнер в статусе Up. Открой личный чат с ботом в Telegram и отправь `/start`: появятся кнопки, а Telegram-команды зарегистрируются автоматически.
5. Нажми **«🔍 Скан сейчас»**, затем **«🧪 Тесты» → «🔬 Проверить API и БД»**. Сканер на новом сервере первоначально на паузе, его можно запускать отдельной кнопкой.

Установщик: скачивает исходники, обновляет проект **только с чистой веткой main**, устанавливает отсутствующие Git/Docker/Compose через apt и собирает контейнер. Он прекращает работу при другом запущенном экземпляре CS2 Trade One, не перезаписывает существующий .env, не включает реальные покупки и не отправляет торговых API-запросов. Если на VPS остался прежний Telegram-бот на том же токене (вне CS2 Trade One), его нужно **сначала остановить**, иначе возникнет конфликт getUpdates.

## Проверка логов
```bash
cd ~/Steam-trade-bot/CS2_Trade_One
docker compose ps
docker compose logs --tail=60 cs2-bot
```

Если Docker требует sudo, используй `sudo docker compose`.

## Безопасный режим
Установщик запускается только если `DRY_RUN=true`, `LIVE_TRADING_ENABLED=false`, `AUTO_BUY_AFTER_FIRST=false`. В конфигурации `SCAN_SCOPE=watchlist` и лимиты покупки остаются без изменений. Данные SQLite сохраняются в Docker volume `cs2_state`.

**Важно:** наличие GitHub Actions с успехом означает лишь, что прошли тесты кода. Оно **не подтверждает**, что VPS подключился к Telegram/Market.CSGO.
