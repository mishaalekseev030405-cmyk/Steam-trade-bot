# VPS deployment (Ubuntu 22.04/24.04, simulation only)

This deploys **read-only monitoring**, not automatic trading. Keep `DRY_RUN=true`. No purchase/sell API calls exist.

## 1. Before deployment
- Ensure the VPS is provisioned, patched, and accessible over SSH with a non-root administrative account.
- Review and merge the deployment PR after CI succeeds. Clone the approved `main` revision, not an unreviewed branch.
- Rotate any Market or Telegram tokens previously posted in chats, screenshots, or logs.
- **Disable the scheduled GitHub Actions monitor** before enabling the VPS scanner to avoid two independent scanners and divergent state.
- Verify Market API currency units, permissions and response fields with the provider before relying on signals.

## 2. Install as an administrator (one time)

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
sudo useradd --system --user-group --home-dir /var/lib/cs2-market-bot --shell /usr/sbin/nologin cs2bot
sudo install -d -o cs2bot -g cs2bot -m 750 /var/lib/cs2-market-bot
sudo git clone https://github.com/mishaalekseev030405-cmyk/Steam-trade-bot.git /opt/cs2-market-bot
sudo chown -R root:root /opt/cs2-market-bot
sudo python3 -m venv /opt/cs2-market-bot/.venv
sudo /opt/cs2-market-bot/.venv/bin/python -m pip install -r /opt/cs2-market-bot/requirements.txt
sudo install -o root -g root -m 600 /opt/cs2-market-bot/.env.example /etc/cs2-market-bot.env
sudo nano /etc/cs2-market-bot.env
```

**Private repo:** git clone requires an authenticated GitHub mechanism (prefer a read-only deploy key); do not embed credentials in the URL or shell history. Never post the env file or tokens in chat.

Initialize the persistent state only on a fresh installation. If you have existing simulated records, back them up and migrate them deliberately instead of overwriting:

```bash
sudo -u cs2bot sh -c 'printf "{\"version\":1,\"operations\":[]}\n" > /var/lib/cs2-market-bot/purchase_ledger.json'
sudo -u cs2bot sh -c 'printf "{\"cursor\":0}\n" > /var/lib/cs2-market-bot/scan_progress.json'
sudo -u cs2bot sh -c 'printf "[]\n" > /var/lib/cs2-market-bot/candidate_history.json'
sudo cp /opt/cs2-market-bot/deploy/systemd/cs2-scanner.service /etc/systemd/system/
sudo cp /opt/cs2-market-bot/deploy/systemd/cs2-scanner.timer /etc/systemd/system/
sudo cp /opt/cs2-market-bot/deploy/systemd/cs2-telegram.service /etc/systemd/system/
sudo systemctl daemon-reload
```

## 3. Validate and start

```bash
sudo -u cs2bot /opt/cs2-market-bot/.venv/bin/python -m unittest discover -s /opt/cs2-market-bot/tests -v
sudo systemctl start cs2-scanner.service
sudo systemctl status cs2-scanner.service --no-pager
sudo systemctl enable --now cs2-scanner.timer cs2-telegram.service
sudo systemctl list-timers --all | grep cs2
sudo journalctl -u cs2-scanner.service -n 60 --no-pager
sudo journalctl -u cs2-telegram.service -n 60 --no-pager
```

For offline preflight with the environment loaded, use `sudo systemctl show ...` only for non-secret metadata; **do not print environment variables**. The service units load the secrets privately from `/etc/cs2-market-bot.env`.

## 4. Stop / rollback

```bash
sudo systemctl disable --now cs2-scanner.timer cs2-telegram.service
sudo systemctl stop cs2-scanner.service
```

Back up `/var/lib/cs2-market-bot` before updates. Keep one Telegram long-polling instance per token. Never run GitHub Actions and the VPS scanner concurrently. There is no live purchase/sale adapter, transactional database, or verified profit execution; these must be built and tested separately before any real-money deployment.
