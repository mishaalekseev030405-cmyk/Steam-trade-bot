# Использованные открытые источники и лицензии

Проверены репозитории и публичные API, а не «сливы» с неизвестным происхождением. Текущий код сборки написан как новый интеграционный проект; сторонние бинарники, архивы и чужие аккаунты не включены.

1. **Существующий Steam-trade-bot** (архитектура сканирования/сигналов/лимитов): https://github.com/mishaalekseev030405-cmyk/Steam-trade-bot — источник, на который ориентирована структура проекта; старые файлы и его данные НЕ изменялись.
2. **market.csgo-autobuyer** от `4hnme` (документирование API закупок и механизма конкретного лота): https://github.com/4hnme/market.csgo-autobuyer — MIT License, Copyright (c) 2022 4hnme, лицензия https://github.com/4hnme/market.csgo-autobuyer/blob/main/LICENSE.md.
3. **cs2-market-bot** от `arseniizyk` (пример Telegram-интерфейса и рыночных источников): https://github.com/arseniizyk/cs2-market-bot — MIT License, Copyright (c) 2025 Arsenii, лицензия https://github.com/arseniizyk/cs2-market-bot/blob/main/LICENSE.
4. **CS2 Signal Bot**: https://github.com/oskemarkup/cs2-bot — изучена архитектура уведомлений, код в сборку не копировался.
5. **Официальная документация Market.CSGO**: https://market.csgo.com/docs-v2, https://market.csgo.com/es/api/content/start.
6. **Официальная документация Telegram Bot API**: https://core.telegram.org/bots/api.

Если в будущей версии будут буквально скопированы части MIT-лицензированных проектов, сохраняйте соответствующие copyright и текст лицензии в дистрибутиве. Настоящий пакет не содержит скопированных файлов этих репозиториев.
