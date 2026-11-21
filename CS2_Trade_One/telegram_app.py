"""Owner-only Telegram panel and scheduled monitoring daemon."""
from __future__ import annotations

import asyncio
import html
import logging
import time
from decimal import Decimal

import httpx

from config import Settings
from market import Market, MarketError
from scanner import run_scan
from store import Store
from trade import TradeError, buy_candidate, reconcile

log = logging.getLogger(__name__)


def fmt(value) -> str:
    return f'{Decimal(str(value)):,.2f}'.replace(',', ' ')


def esc(value) -> str:
    return html.escape(str(value))


class App:
    def __init__(self, cfg: Settings, market: Market, store: Store):
        self.cfg, self.market, self.store = cfg, market, store
        self.tg = httpx.AsyncClient(timeout=httpx.Timeout(40, connect=10))
        self.scan_lock = asyncio.Lock()
        self.trade_lock = asyncio.Lock()
        self.api = f'https://api.telegram.org/bot{cfg.telegram_token}'

    async def close(self):
        await self.tg.aclose()
        self.market.close()

    async def telegram(self, method: str, payload: dict):
        resp = await self.tg.post(f'{self.api}/{method}', json=payload)
        resp.raise_for_status()
        obj = resp.json()
        if not obj.get('ok'):
            raise RuntimeError('Telegram API rejected request')
        return obj.get('result')

    async def show(self, text: str, buttons: list[list[tuple[str, str]]] | None = None,
                   message_id: int | None = None):
        keyboard = {'inline_keyboard': [[{'text': text, 'callback_data': code}
                                        for text, code in line]
                                       for line in (buttons or self.menu())]}
        payload = {'chat_id': self.cfg.owner_id, 'text': text, 'parse_mode': 'HTML',
                   'reply_markup': keyboard, 'disable_web_page_preview': True}
        if message_id is not None:
            try:
                await self.telegram('editMessageText', {**payload, 'message_id': message_id})
                return
            except (httpx.HTTPError, RuntimeError):
                pass
        await self.telegram('sendMessage', payload)

    def menu(self):
        scan = self.store.get('scanning') == '1'
        alerts = self.store.get('notifications', '1') == '1'
        return [
            [('🏠 Главная', 'home'), ('💎 Находки', 'finds')],
            [('🔍 Скан сейчас', 'scan'), ('⏹ Стоп' if scan else '▶️ Запуск', 'toggle')],
            [('💰 Бюджет', 'budget'), ('💳 Баланс', 'balance')],
            [('📜 История', 'history'), ('🔄 Сверка', 'sync')],
            [('📡 Диагностика', 'diagnostics'), ('🧪 Тесты', 'tests')],
            [('🔔 Уведомл. ВКЛ' if alerts else '🔕 Уведомл. ВЫКЛ', 'notifications'),
             ('🛡 Защита', 'security')],
            [('⚙️ Настройки', 'settings'), ('❓ Помощь', 'help')],
        ]

    def home(self) -> str:
        info = self.store.overview(self.cfg)
        mode = '🔒 <b>Реальная покупка разрешена</b>' if self.cfg.live_ready else '🧪 <b>DRY_RUN — только тест</b>'
        return (
            '🎮 <b>CS2 TRADE ONE</b>\n\n'
            f'{mode}\n'
            f'Поиск: {"▶️ включен" if self.store.get("scanning") == "1" else "⏸ остановлен"}\n'
            f'Бюджет: {fmt(self.cfg.budget_rub)} ₽\n'
            f'Зарезервировано: {fmt(info["reserved_rub"])} ₽\n'
            f'Свободно: {fmt(info["remaining_rub"])} ₽\n'
            f'Активных позиций: {info["positions"]} / {self.cfg.max_positions}\n'
            f'Незавершённых: {info["unresolved"]}\n'
            f'Последний скан: {esc(self.store.get("last_scan", "нет"))[:30]}\n'
            f'Предметов в последнем скане: {esc(self.store.get("last_scan_count", "0"))}\n'
            f'Подходящих лотов: {esc(self.store.get("last_scan_found", "0"))}\n\n'
            '⚠️ Любая прибыль здесь — предварительная оценка.')

    def finds(self) -> tuple[str, list[list[tuple[str,str]]]]:
        options = self.store.candidates(5)
        lines = ['💎 <b>Кандидаты за последние 15 минут</b>',
                 'Цена продажи — текущая заявка, не гарантированный доход.']
        buttons = []
        for item in options:
            lines.append(f'\n<b>{esc(item["name"])}</b>\n'
                         f'Лот: <code>{esc(item["item_id"])}</code>\n'
                         f'Покупка: {fmt(Decimal(item["ask_kopecks"]) / 100)} ₽\n'
                         f'Buy-ордер: {fmt(item["bid_rub"])} ₽\n'
                         f'Оценка чистой прибыли: {fmt(item["profit_rub"])} ₽\n'
                         f'ROI: {fmt(item["roi_percent"])}%; продажи 7д: {item["sales_7d"]}')
            buttons.append([(f'🛒 Проверить {item["item_id"]}', 'review:' + item['item_id'])])
        if not options:
            lines.append('\nНет актуальных кандидатов. Можно запустить скан.')
        buttons.append([('🏠 Меню', 'home')])
        return '\n'.join(lines), buttons

    def settings_text(self) -> str:
        return (f'⚙️ <b>НАСТРОЙКИ</b>\n\n'
                f'Режим: {"LIVE (с ручным подтверждением)" if self.cfg.live_ready else "DRY_RUN"}\n'
                f'Автопокупки после первой: {"включены" if self.auto_allowed() else "выключены"}\n'
                f'Обзор: {esc(self.cfg.scope)} / каждые {self.cfg.scan_every_s} сек\n'
                f'Цена: {fmt(self.cfg.min_item_rub)}–{fmt(self.cfg.max_item_rub)} ₽\n'
                f'Прибыль: от {fmt(self.cfg.min_profit_rub)} ₽\n'
                f'ROI: от {fmt(self.cfg.min_roi_percent)}%\n'
                f'Продаж за 7д: от {self.cfg.min_sales_7d}\n'
                f'Комиссия расчёта: {self.cfg.sell_fee * 100}%\n\n'
                'Продажа скинов из Telegram пока не включена: требуется проверка инвентаря и Steam-трейдов.')

    def budget_text(self) -> str:
        info = self.store.overview(self.cfg)
        return (
            '💰 <b>БЮДЖЕТ И ПОЗИЦИИ</b>\n\n'
            f'Лимит: <b>{fmt(self.cfg.budget_rub)} ₽</b>\n'
            f'Зарезервировано: {fmt(info["reserved_rub"])} ₽\n'
            f'Свободно по лимиту: {fmt(info["remaining_rub"])} ₽\n'
            f'Активных позиций: {info["positions"]} / {self.cfg.max_positions}\n'
            f'Незавершённых операций: {info["unresolved"]}\n'
            f'Цена одного скина: {fmt(self.cfg.min_item_rub)}–{fmt(self.cfg.max_item_rub)} ₽\n\n'
            '⚠️ Это внутренний учёт бота, не реальный остаток кошелька. '
            'Баланс Market.CSGO — в разделе «Баланс».'
        )

    def diagnostics_text(self) -> str:
        # Never forward raw HTTP errors, URLs or secret-bearing exception strings.
        err = '⚠️ Ошибка — смотри логи сервера' if self.store.get('last_error') else '✅ Нет'
        return (
            '📡 <b>ДИАГНОСТИКА</b>\n\n'
            'Панель Telegram: ✅ отвечает\n'
            f'Сканирование: {"🟢 включено" if self.store.get("scanning") == "1" else "⏸ на паузе"}\n'
            f'Последний скан: {esc(self.store.get("last_scan", "нет"))[:40]}\n'
            f'Просмотрено предметов: {esc(self.store.get("last_scan_count", "0"))[:20]}\n'
            f'Кандидатов: {esc(self.store.get("last_scan_found", "0"))[:20]}\n'
            f'Курсор: {esc(self.store.get("cursor", "0"))[:20]}\n'
            f'Ошибка: {err}\n'
            f'Интервал: {self.cfg.scan_every_s} сек\n'
            'Данные операций: SQLite\n\n'
            'Нажми «🧪 Тесты» для безопасной проверки API.'
        )

    def tests_text(self) -> str:
        return (
            '🧪 <b>ТЕСТИРОВАНИЕ БОТА</b>\n\n'
            'В проекте есть автоматические проверки расчётов, лимитов, '
            'копеек/рублей, повторных покупок и тайм-аутов.\n\n'
            '<b>Перед торговлей необходимо:</b>\n'
            '1. Сверить цены и валюту с Market.CSGO.\n'
            '2. Проверить актуальность buy-ордеров и комиссию.\n'
            '3. Проверить кнопки и защиту доступа Telegram.\n'
            '4. Провести 20 виртуальных сделок.\n'
            '5. Перезапустить сервер и проверить SQLite.\n'
            '6. Проверить стабильность работы 24 часа.\n'
            '7. Проверить первую реальную сделку только с разрешения владельца.\n\n'
            '🔬 Самопроверка ниже читает баланс и котировки, '
            '<b>никогда не покупает и не продаёт</b>.'
        )

    def security_text(self) -> str:
        info = self.store.overview(self.cfg)
        return (
            '🛡 <b>БЕЗОПАСНОСТЬ</b>\n\n'
            f'Торговля: {"⚠️ LIVE разрешён на сервере" if self.cfg.live_ready else "🔒 DRY_RUN (без списаний)"}\n'
            f'Автопокупка: {"⚠️ разрешена" if self.auto_allowed() else "🔒 отключена"}\n'
            f'Лимит на лот: {fmt(self.cfg.max_item_rub)} ₽\n'
            f'Общий бюджет: {fmt(self.cfg.budget_rub)} ₽\n'
            f'Позиций максимум: {self.cfg.max_positions}\n'
            f'Минимальная расчётная прибыль: {fmt(self.cfg.min_profit_rub)} ₽\n'
            f'Минимальный ROI: {fmt(self.cfg.min_roi_percent)}%\n'
            f'Незавершённых покупок: {info["unresolved"]}\n\n'
            '🔐 Первую покупку подтверждает владелец; цена перепроверяется.\n'
            '🚫 Автоматическая продажа не реализована.\n'
            'Изменить LIVE/DRY_RUN через Telegram нельзя.'
        )

    def help_text(self) -> str:
        return (
            '❓ <b>ПОМОЩЬ</b>\n\n'
            '🔍 Скан — разовая проверка рынка.\n'
            '▶️/⏹ — запуск или пауза поиска в работающем CS2 Trade One.\n'
            '💎 Находки — свежие кандидаты за 15 минут.\n'
            '💰 Бюджет — локальные лимиты, 💳 Баланс — API площадки.\n'
            '📜 История — операции, 🔄 Сверка — незавершённые сделки.\n'
            '🧪 Тесты — безопасная проверка API.\n'
            '🔔 Уведомления — оповещения о новых находках.\n\n'
            'Команды: /start /menu /status /scan /tests /help\n'
            '⚠️ Пауза здесь не отключает отдельный GitHub Actions workflow.\n'
            'Оценочная прибыль не гарантирует продажу.'
        )

    async def selftest(self) -> str:
        """Read-only API and SQLite checks; NO buying/selling endpoints."""
        lines = ['🔬 <b>САМОПРОВЕРКА (БЕЗ ПОКУПОК)</b>']
        try:
            info = await asyncio.to_thread(self.store.overview, self.cfg)
            lines.append(f'✅ База SQLite: доступна; позиций {info["positions"]}')
        except Exception:
            lines.append('❌ SQLite: ошибка чтения')
        try:
            balance = await asyncio.to_thread(self.market.balance)
            lines.append(f'✅ Баланс Market.CSGO: {fmt(balance)} ₽')
        except Exception as exc:
            lines.append(f'❌ API баланса: {esc(type(exc).__name__)}')
        try:
            quotes = await asyncio.to_thread(self.market.buy_order_quotes)
            lines.append(f'✅ Котировки buy-ордеров: {len(quotes)} названий')
        except Exception as exc:
            lines.append(f'❌ API котировок: {esc(type(exc).__name__)}')
        lines.append('🔒 Торговые запросы не отправлялись.')
        lines.append('⚠️ Это не заменяет unit-тесты и проверку на реальных сделках.')
        return '\n'.join(lines)

    def auto_allowed(self) -> bool:
        return (self.cfg.live_ready and self.cfg.enable_auto_after_first
                and self.store.get('auto') == '1'
                and self.store.overview(self.cfg)['confirmed'] > 0)

    async def report(self, items: list[dict]) -> None:
        if not items:
            return
        if self.store.get('notifications', '1') != '1':
            self.store.mark_alerted([x['item_id'] for x in items])
            return
        text = '🔔 <b>Новые кандидаты CS2</b>\n\n'
        text += '\n'.join(f'{esc(x["name"])} — {fmt(x["ask_kopecks"] / 100)} ₽, '
                          f'теор. прибыль {fmt(x["profit_rub"])} ₽'
                          for x in items)
        text += '\n\nОткрой «Находки» для проверки лота.'
        await self.show(text)
        self.store.mark_alerted([x['item_id'] for x in items])

    async def scan(self):
        if self.scan_lock.locked():
            return 'Сканирование уже идёт.'
        async with self.scan_lock:
            try:
                fresh = await asyncio.to_thread(run_scan, self.cfg, self.market, self.store)
                await self.report(fresh)
                self.store.set('last_error', '')
                if self.auto_allowed() and self.store.overview(self.cfg)['unresolved'] == 0:
                    best = self.store.candidates(1)
                    if best:
                        try:
                            await self.purchase(best[0]['item_id'], auto=True)
                        except (TradeError, MarketError) as exc:
                            log.warning('Auto buy skipped: %s', exc)
                return '✅ Проверка завершена. Результаты — в «Находках».'
            except Exception as exc:
                log.exception('Scan failed')
                self.store.set('last_error', f'{type(exc).__name__}: {str(exc)[:120]}')
                return f'⚠️ Сканер: {esc(type(exc).__name__)}. Подробности — в логах сервера.'

    async def purchase(self, item_id: str, auto: bool = False) -> str:
        if self.trade_lock.locked():
            raise TradeError('Другая покупка уже проверяется')
        async with self.trade_lock:
            text = await asyncio.to_thread(buy_candidate, item_id, self.cfg,
                                           self.market, self.store)
            if auto:
                try:
                    await self.show('🤖 Автопокупка: ' + esc(text))
                except (httpx.HTTPError, RuntimeError):
                    log.error('Auto purchase notification failed')
            return text

    async def handle(self, code: str, message_id: int | None = None):
        if code == 'home':
            await self.show(self.home(), message_id=message_id)
        elif code == 'finds':
            text, buttons = self.finds()
            await self.show(text, buttons, message_id)
        elif code == 'budget':
            await self.show(self.budget_text(), message_id=message_id)
        elif code == 'diagnostics':
            await self.show(self.diagnostics_text(), message_id=message_id)
        elif code == 'tests':
            await self.show(self.tests_text(),
                            [[('🔬 Проверить API и БД', 'selftest'), ('🏠 Меню', 'home')]],
                            message_id)
        elif code == 'selftest':
            await self.show('🔬 Читаю данные API и SQLite…',
                            [[('🏠 Меню', 'home')]], message_id)
            outcome = await self.selftest()
            await self.show(outcome,
                            [[('🔄 Повторить', 'selftest'), ('🏠 Меню', 'home')]])
        elif code == 'security':
            await self.show(self.security_text(), message_id=message_id)
        elif code == 'help':
            await self.show(self.help_text(), message_id=message_id)
        elif code == 'notifications':
            value = '0' if self.store.get('notifications', '1') == '1' else '1'
            self.store.set('notifications', value)
            await self.show('🔔 Уведомления о новых находках ' +
                            ('включены.' if value == '1' else 'выключены.') +
                            '\nУведомления о критических ошибках остаются включёнными.',
                            message_id=message_id)
        elif code == 'settings':
            await self.show(self.settings_text(),
                            [[('🤖 Автопокупки ВКЛ/ВЫКЛ', 'auto'), ('🏠 Меню', 'home')]], message_id)
        elif code == 'auto':
            if not self.cfg.live_ready or not self.cfg.enable_auto_after_first:
                await self.show('🔒 Автопокупки запрещены настройками сервера.', message_id=message_id)
            elif self.store.overview(self.cfg)['confirmed'] < 1:
                await self.show('🔒 Сначала нужна первая подтверждённая покупка вручную.', message_id=message_id)
            else:
                new = '0' if self.store.get('auto') == '1' else '1'
                self.store.set('auto', new)
                await self.show(f'Автопокупки {"включены" if new == "1" else "выключены"}.', message_id=message_id)
        elif code == 'toggle':
            new = '0' if self.store.get('scanning') == '1' else '1'
            self.store.set('scanning', new)
            await self.show(f'Поиск {"включён" if new == "1" else "остановлен"}.', message_id=message_id)
        elif code == 'scan':
            await self.show('🔎 Запускаю проверку...', message_id=message_id)
            outcome = await self.scan()
            await self.show(outcome)
        elif code == 'balance':
            try:
                balance = await asyncio.to_thread(self.market.balance)
                text = f'💳 Баланс Market.CSGO: {fmt(balance)} ₽\n{self.home()}'
            except Exception as exc:
                text = f'⚠️ Не удалось прочитать баланс: {esc(type(exc).__name__)}'
            await self.show(text, message_id=message_id)
        elif code == 'history':
            ops = self.store.history()
            text = '🧾 <b>История операций</b>\n'
            for op in ops:
                text += (f'\n{esc(op["name"])}\n{fmt(Decimal(op["ask_kopecks"]) / 100)} ₽ '
                         f'— {esc(op["status"])}\n')
            if not ops:
                text += '\nПока пусто.'
            await self.show(text, message_id=message_id)
        elif code == 'sync':
            try:
                text = await asyncio.to_thread(reconcile, self.cfg, self.market, self.store)
            except Exception as exc:
                text = f'⚠️ Не удалось сверить покупки: {type(exc).__name__}'
            await self.show(esc(text), message_id=message_id)
        elif code.startswith('review:'):
            item_id = code.split(':', 1)[1]
            item = self.store.candidate(item_id)
            if not item or item not in self.store.candidates(100):
                await self.show('Лот уже устарел. Запусти новый скан.', message_id=message_id)
                return
            action = 'ПОТРАТИТЬ РЕАЛЬНЫЕ ДЕНЬГИ' if self.cfg.live_ready else 'СИМУЛИРОВАТЬ'
            text = (f'⚠️ <b>Подтвердить действие?</b>\n{esc(item["name"])}\n'
                    f'Лот <code>{esc(item_id)}</code>, цена {fmt(Decimal(item["ask_kopecks"]) / 100)} ₽\n'
                    f'Действие: <b>{action}</b>\n\n'
                    'Перед покупкой цена и заявка проверяются повторно. Прибыль не гарантирована.')
            await self.show(text, [[('✅ Подтвердить', 'confirm:'+item_id)],
                                   [('❌ Отмена', 'finds')]], message_id)
        elif code.startswith('confirm:'):
            item_id = code.split(':', 1)[1]
            # Remove the one-click confirmation button immediately.
            await self.show('⏳ Проверяю цену и выполняю команду. Не нажимай повторно.',
                            [[('🏠 Меню', 'home')]], message_id)
            try:
                response = await self.purchase(item_id)
            except (TradeError, MarketError, RuntimeError, ValueError) as exc:
                response = f'⚠️ {exc}'
            await self.show(esc(response))
        else:
            await self.show(self.home(), message_id=message_id)

    async def updates(self):
        offset = int(self.store.get('tg_offset', '0'))
        while True:
            try:
                events = await self.telegram('getUpdates', {
                    'offset': offset, 'timeout': 25,
                    'allowed_updates': ['message', 'callback_query']})
                for event in events:
                    offset = max(offset, event['update_id'] + 1)
                    self.store.set('tg_offset', str(offset))
                    cb = event.get('callback_query')
                    msg = event.get('message')
                    sender = (cb or msg or {}).get('from', {})
                    chat = ((cb or {}).get('message', {}) if cb else msg or {}).get('chat', {})
                    # Never reveal account information or run commands for others.
                    if sender.get('id') != self.cfg.owner_id or chat.get('type') != 'private' or chat.get('id') != self.cfg.owner_id:
                        if cb:
                            await self.telegram('answerCallbackQuery', {'callback_query_id': cb['id']})
                        continue
                    if cb:
                        await self.telegram('answerCallbackQuery', {'callback_query_id': cb['id']})
                        await self.handle(cb.get('data', 'home'), cb.get('message', {}).get('message_id'))
                    elif msg:
                        raw_command = (msg.get('text') or '').split(maxsplit=1)
                        command = (raw_command[0].split('@', 1)[0].lower()
                                   if raw_command else '')
                        routes = {'/start': 'home', '/menu': 'home',
                                  '/status': 'home', '/scan': 'scan',
                                  '/tests': 'tests', '/help': 'help'}
                        await self.handle(routes.get(command, 'home'))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Telegram URL contains bot token: never log raw HTTP exceptions.
                log.error('Telegram polling failed: %s', type(exc).__name__)
                await asyncio.sleep(5)

    async def scan_loop(self):
        while True:
            if self.store.get('scanning') == '1':
                outcome = await self.scan()
                if outcome.startswith('⚠️'):
                    try:
                        await self.show(outcome)
                    except (httpx.HTTPError, RuntimeError):
                        log.error('Cannot send scan warning')
            await asyncio.sleep(self.cfg.scan_every_s)

    async def run(self):
        try:
            await self.show('✅ CS2 Trade One запущен.\n'+self.home())
            await asyncio.gather(self.updates(), self.scan_loop())
        finally:
            await self.close()
