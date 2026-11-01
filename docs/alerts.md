# Alerts setup

Turn alerts on in **Settings → Alerts**, pick what triggers them, fill in at least one channel, save, then click **Send test**. Each token alerts at most once every 6 hours.

## ntfy (easiest, no account)

1. Install the **ntfy** app (iOS / Android) or open https://ntfy.sh.
2. Subscribe to a topic with a long random name, for example `kraken-7f3k2q9x`. Topics are public, so anyone who guesses the name can read it.
3. Put the same name in **ntfy.sh topic**.

## Telegram

1. Message **@BotFather**, send `/newbot`, and copy the bot token.
2. Send any message to your new bot.
3. Get your chat ID from **@userinfobot**.
4. Fill in **Telegram bot token** and **Telegram chat ID**.

## Discord

1. In your server: **Server settings → Integrations → Webhooks → New webhook**, pick a channel, then **Copy webhook URL**.
2. Paste it into **Discord webhook URL**.

Tokens and webhook URLs are stored in `data/settings.json` on your computer and are never shown again in the UI after saving.
