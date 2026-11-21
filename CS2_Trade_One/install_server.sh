#!/usr/bin/env bash
# Interactive installer/updater for the owner's Ubuntu VPS.
# No real trading and no secrets are sent to GitHub or to ChatGPT.
set -Eeuo pipefail
umask 077

REPOSITORY="https://github.com/mishaalekseev030405-cmyk/Steam-trade-bot.git"
TARGET="$HOME/Steam-trade-bot"
if [ "$#" -gt 0 ]; then TARGET="$1"; fi

info() { printf '\n%s\n' "$*"; }
fail() { printf '\nОШИБКА: %s\n' "$*" >&2; exit 1; }
asroot() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }
docker_cmd() {
  if docker info >/dev/null 2>&1; then docker "$@"; else sudo docker "$@"; fi
}

[ -t 0 ] || fail "Открой интерактивный SSH-терминал и запусти этот файл напрямую."
command -v apt-get >/dev/null || fail "Нужна Ubuntu/Debian с apt-get."
info "CS2 Trade One — установка Telegram-панели на VPS."
info "Будут проверены Git и Docker; торговля остаётся только в DRY_RUN."
printf 'Продолжить установку? [д/Н] '
read -r consent </dev/tty
case "$consent" in д|Д|y|Y|yes|YES) ;; *) exit 0 ;; esac

if ! command -v git >/dev/null; then
  asroot apt-get update
  asroot apt-get install -y git
fi

if ! command -v docker >/dev/null; then
  asroot apt-get update
  asroot apt-get install -y docker.io
fi
if command -v systemctl >/dev/null; then
  asroot systemctl enable --now docker >/dev/null
fi
docker_cmd info >/dev/null || fail "Docker недоступен. Проверь права и службу docker."

if ! docker_cmd compose version >/dev/null 2>&1; then
  asroot apt-get update
  if ! asroot apt-get install -y docker-compose-v2; then
    asroot apt-get install -y docker-compose-plugin ||
      fail "Docker Compose v2 не установлен. Проверь репозитории Docker/Ubuntu."
  fi
fi
docker_cmd compose version >/dev/null 2>&1 ||
  fail "Нужна работающая команда docker compose."

if [ -d "$TARGET/.git" ]; then
  origin="$(git -C "$TARGET" remote get-url origin)"
  case "$origin" in
    "https://github.com/mishaalekseev030405-cmyk/Steam-trade-bot.git"|"https://github.com/mishaalekseev030405-cmyk/Steam-trade-bot"|"git@github.com:mishaalekseev030405-cmyk/Steam-trade-bot.git") ;;
    *) fail "В папке другой Git-репозиторий. Укажи отдельную папку аргументом." ;;
  esac
  [ -z "$(git -C "$TARGET" status --porcelain)" ] ||
    fail "Есть локальные изменения. Сохрани их перед обновлением Git."
  [ "$(git -C "$TARGET" branch --show-current)" = "main" ] ||
    fail "Текущая ветка не main. Проверь проект вручную."
  git -C "$TARGET" pull --ff-only origin main
elif [ ! -e "$TARGET" ]; then
  git clone --depth 1 --branch main "$REPOSITORY" "$TARGET"
else
  fail "Папка существует и не является нужным Git-репозиторием: $TARGET"
fi

cd "$TARGET/CS2_Trade_One" ||
  fail "Папка CS2_Trade_One не найдена."
APP_DIR="$(pwd -P)"

# Avoid running a second copy from a different Compose working directory.
while IFS= read -r cid; do
  [ -z "$cid" ] && continue
  other="$(docker_cmd inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$cid" 2>/dev/null || true)"
  if [ -n "$other" ] && [ "$other" != "$APP_DIR" ]; then
    fail "Уже есть другой Docker-экземпляр CS2 Trade One в $other. Сначала останови старый, иначе Telegram polling конфликтует."
  fi
done < <(docker_cmd ps --filter label=com.docker.compose.service=cs2-bot --format '{{.ID}}')

if [ ! -f .env ]; then
  info "Первый запуск: введи доступы в SSH-терминале сервера (не в ChatGPT)."
  printf 'Числовой Telegram ID владельца: '
  read -r owner </dev/tty
  [[ "$owner" =~ ^[1-9][0-9]*$ ]] ||
    fail "Telegram ID должен быть положительным числом."

  read -r -s -p 'Токен Telegram-бота (ввод скрыт): ' token </dev/tty
  printf '\n'
  read -r -s -p 'API-ключ Market.CSGO (ввод скрыт): ' market_key </dev/tty
  printf '\n'
  [ -n "$token" ] && [ -n "$market_key" ] ||
    fail "Токен и API-ключ обязательны."
  [[ "$token" != *[[:space:]]* && "$market_key" != *[[:space:]]* ]] ||
    fail "Пробельные символы в секретах недопустимы."

  tmp="$(mktemp .env.new.XXXXXX)"
  {
    printf 'MARKET_CSGO_API_KEY=%s\n' "$market_key"
    printf 'TELEGRAM_BOT_TOKEN=%s\n' "$token"
    printf 'TELEGRAM_OWNER_ID=%s\n' "$owner"
    grep -Ev '^(MARKET_CSGO_API_KEY|TELEGRAM_BOT_TOKEN|TELEGRAM_OWNER_ID)=' .env.example
  } > "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" .env
  unset token market_key
  info "Настройки сохранены только на VPS в защищённом .env."
fi

# Refuse to redeploy if an existing configuration could spend real money.
python3 - <<'PY'
from pathlib import Path
import sys
values = {}
for line in Path('.env').read_text(encoding='utf-8').splitlines():
    if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    values[key.strip()] = value.strip().strip('"').strip("'")
needed = ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_OWNER_ID', 'MARKET_CSGO_API_KEY')
if any(not values.get(key) for key in needed) or not values['TELEGRAM_OWNER_ID'].isdigit() or int(values['TELEGRAM_OWNER_ID']) <= 0:
    sys.exit('Неполная .env: проверь токен, ID владельца и ключ Market.CSGO.')
if (values.get('DRY_RUN', '').lower() != 'true'
    or values.get('LIVE_TRADING_ENABLED', '').lower() != 'false'
    or values.get('AUTO_BUY_AFTER_FIRST', '').lower() != 'false'):
    sys.exit('Безопасность: DRY_RUN=true, LIVE_TRADING_ENABLED=false, AUTO_BUY_AFTER_FIRST=false обязательны для установщика.')
print('Настройки безопасности проверены: реальная торговля отключена.')
PY
chmod 600 .env

info "Собираю Docker-образ и запускаю один экземпляр Telegram-бота..."
docker_cmd compose up -d --build --remove-orphans
docker_cmd compose ps
info "Если статус контейнера Up, открой Telegram-бота и отправь /start."
info "Панель: Главная, Находки, Скан, Бюджет, Баланс, История, Сверка, Диагностика, Тесты, Защита."
info "Сканер в новой базе по умолчанию на паузе. Нажми «Сканировать» для разового поиска."
info "Логи для проверки: cd \"$APP_DIR\" && docker compose logs --tail=50 cs2-bot"
