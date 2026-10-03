# NOVA Sentinel

A small tool that reads one or more self-selected screen areas via screenshot
and OCR (e.g. an item count or carry weight in a game) and warns when a value
goes above or below a threshold. Control and display happen through a small
web dashboard, reachable on your own WiFi network (e.g. from your phone).

**by Grigorios Gkisios ~ Hobby Developer**

I additionally used an AI tool (Claude by Anthropic) during development,
which is pretty normal these days. Concept, requirements, architecture
decisions, debugging, and all testing came from me; the AI assisted with
writing the code based on my specifications.

---

## Features

- **Up to 3 independent observation points** at once, each with its own name,
  target area, and alert type
- Interactive target selection by dragging a rectangle, no need to manually
  enter screen coordinates
- Two alert types per point: warn when a value drops **below** a threshold
  (e.g. item stock), or warn when a value rises **above** a percentage of a
  maximum (e.g. carry weight)
- Traffic-light colors and audible warnings for critical values, with
  different tones depending on the event
- **Phone notifications** via your choice of: a generic webhook (Discord,
  Slack, etc.), Telegram, or ntfy.sh — pick whichever you like, or use
  several at once
- Web dashboard (accessible via browser, no app installation needed)
- Optional HTTPS with a self-signed certificate

## Installation

```
pip install mss pillow pytesseract cryptography
```

[Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) is also
required as a separate program (not installable via pip).

## Start

```
python zahl_warner_app.py
```

Open the displayed address in a browser (PC or phone on the same WiFi).
Click **"+ Add observation point"** in the app, then drag a rectangle around
a number on your PC screen. Repeat for up to 3 points. Set each point's name,
alert type and thresholds directly in the app, then press **Start**.

## Phone Notifications

Set up any combination of the following in the app's settings panel:

- **Webhook URL**: works out of the box with Discord and Slack-style
  incoming webhooks.
- **Telegram**: create a bot via `@BotFather`, message it once, then read
  your chat ID from `https://api.telegram.org/bot<TOKEN>/getUpdates`.
- **ntfy.sh**: install the free ntfy app, subscribe to a topic of your
  choice (make it long and random), and enter the same topic name here. No
  account needed.

Use the **"Send Test Notification"** button to verify your setup before
relying on it.

---

## Privacy / Data Handling

This tool does not collect, store, or transmit any data to third parties or
to the developer, beyond the notifications you explicitly configure
yourself (see above). That's why a separate privacy policy is deliberately
omitted:

- All screenshots and recognized values are processed **exclusively locally
  on your own machine** (text recognition via Tesseract, also local).
- The web interface is **only reachable within your own home network
  (WiFi)** — there is no external server and no cloud connection run by the
  developer.
- Notifications (webhook/Telegram/ntfy) are sent **directly from your own
  machine to the service you configured** — the developer never sees this
  traffic or any of your data.
- **No account data, passwords, or personal data** are processed or stored
  by this tool itself.
- The developer has **no access whatsoever** to the data or usage of other
  people who use this tool.

Since no data processing in the sense of the GDPR takes place by the
provider/developer (this tool is purely local software with no server
component of its own), no privacy policy is required. This is not legal
advice, just a transparent explanation of how the tool works.

## Note on Third-Party Game Terms of Service

This tool does not interact with game processes (no input injection, no
memory access, no client modification) and only reads screen areas of your
own screen via screenshot. That said, the terms of service of individual
games or platforms may still restrict third-party software in general. It
is the responsibility of the user to clarify this with the relevant
provider before use.

## License

Use at your own risk. No support or warranty claims.
