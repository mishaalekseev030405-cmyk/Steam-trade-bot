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
        return [
            [('📊 Сводка', 'home'), ('💎 Находки', 'finds')],
            [('🔍 Сканировать', 'scan'), ('⏹ Пауза' if scan else '▶️ Старт', 'toggle')],
            [('💳 Баланс', 'balance'), ('🧾 Сделки', 'history')],
            [('⚙️ Режим', 'settings'), ('🔄 Сверить покупки', 'sync')],
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

    def auto_allowed(self) -> bool:
        return (self.cfg.live_ready and self.cfg.enable_auto_after_first
                and self.store.get('auto') == '1'
                and self.store.overview(self.cfg)['confirmed'] > 0)

    async def report(self, items: list[dict]) -> None:
        if not items:
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
                        await self.handle('home')
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
