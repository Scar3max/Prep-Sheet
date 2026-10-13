# Prep Sheet

Prep Sheet is a small-cafe prep planner for a bakery or counter in India. Its synthetic-data demo ingests sales notes, corrects for sell-outs, forecasts demand, converts that into prep quantities, and writes a short practical brief. Its local Telegram bot can collect a cafe's menu and daily sales, then produce a basic prep plan from those saved records.

## What this project does

- Parses owner notes such as "sold 14 croissants, 9 cold coffees, puffs gone by 4pm, binned 6 muffins" into structured rows.
- Corrects obvious sell-out bias by treating recorded sales as a lower bound when a stock-out happened.
- Builds a simple per-item demand feature table from synthetic cafe data.
- Forecasts demand with a local heuristic by default, or the official Prior Labs TabPFN client when explicitly selected.
- Converts demand into a prep quantity using a simple newsvendor-style ratio.
- Generates a short morning brief with a local template by default, or Gemini when explicitly selected and configured.
- Reports which providers ran successfully and which outputs used a local fallback.
- Provides a demo mode that replays 120 synthetic days and writes results to `results/demo_results.json`.
- Provides a Telegram bot with per-chat SQLite storage for menu and sales records.

## Repo layout

```text
prep-sheet/
  README.md
  LICENSE
  .env.example
  config.example.toml
  menu.example.toml
  .github/workflows/tests.yml
  data/
    raw/
    cache/
  src/prepsheet/
    __init__.py
    __main__.py
    ledger.py
    notes.py
    extract.py
    demand.py
    features.py
    forecast.py
    prep.py
    brief.py
    bot.py
    voice.py
    evaluate.py
  tests/
  results/
```

## Quick start

```powershell
cd prep-sheet
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m prepsheet demo
```

The default demo uses local implementations and does not need API keys. To use the optional hosted TabPFN client, install the extra:

```powershell
python -m pip install -e ".[tabpfn]"
```

Then set the TabPFN token and provider selection in your private `.env`:

```dotenv
TABPFN_TOKEN=your_tabpfn_token
FORECAST_PROVIDER=tabpfn
```

Or select TabPFN for a single demo run with `python -m prepsheet demo --forecast-provider tabpfn`.

## Demo mode

```bash
python -m prepsheet demo
```

This replays a synthetic 120-day ledger through the pipeline and writes the summary to `results/demo_results.json`. The JSON marks its data source as `synthetic`. If you only add `TABPFN_TOKEN` but leave `FORECAST_PROVIDER=template` (the default), the demo continues to use the local forecast. Select TabPFN with `FORECAST_PROVIDER=tabpfn` or the `--forecast-provider tabpfn` flag to make a hosted TabPFN attempt.

## Telegram bot

Create a bot with Telegram's BotFather and add its token to your private `.env` as `TELEGRAM_BOT_TOKEN=...`. Start the bot locally:

```powershell
python -m prepsheet telegram
```

In a private chat with the bot, send `/id` to get your chat ID. Add it to `.env` as `TELEGRAM_ALLOWED_CHAT_IDS=123456789`, restart the bot, then send `/menu`. The ID allowlist is required before menu or sales data can be accessed. Group chats are not served.

Menu entry is one row per line in `Name | selling price | unit cost` format, for example `Tea | 25 | 8`. Sales entry is one row per menu item in `Name | made | sold | sold out (yes/no)` format, for example `Tea | 20 | 20 | yes`. Use `/sales YYYY-MM-DD` to enter a past date, or `/sales` for today. The bot shows a formatted review; send `/confirm` to save it or `/cancel` to discard it. `/help` lists the commands.

`/menu list` shows your saved menu with prices and costs. `/prep` displays a titled next-day prep brief and reports whether Gemini or the local template supplied its wording. It calculates quantities from each item's last seven recorded sales rows, treating a stock-out day's made quantity as a lower-bound demand estimate. It uses your saved menu prices/costs and recorded sales, not the synthetic demo ledger. **The Telegram prep forecast currently uses a local recent-average calculation. It does not use TabPFN**, even if `TABPFN_TOKEN` and `FORECAST_PROVIDER=tabpfn` are set; that provider selection applies to the synthetic CLI demo only. If `BRIEF_PROVIDER=gemini` is selected, the structured prep summary (item names, quantities, reasons, and forecast values) is sent to Gemini to phrase the brief and may use API quota; otherwise it uses a local template. SQLite data is stored in `data/prepsheet.sqlite3`, per Telegram chat ID. Keep the bot process running in a terminal; stop it with Ctrl+C. This is local long polling, not a public webhook or deployed always-on bot.

## Using the hosted providers

Copy `.env.example` to `.env` and put your own credentials in `.env` (never in `.env.example` or source control). Do not share or commit `.env`. The CLI loads `.env` automatically; already-set process environment variables take precedence.

To explicitly run both hosted providers:

```powershell
python -m prepsheet demo --forecast-provider tabpfn --brief-provider gemini
```

Hosted calls can use account quota. The TabPFN demo fits one regression model on the generated synthetic ledger's item/context features and synthetic `true_demand` target labels, then predicts the next day for each menu item. This is a demo path, not a trained real-cafe forecasting system. Gemini receives the structured prep summary to produce the brief. The default brief model is `gemini-3.5-flash-lite`, with a retry for transient service/rate-limit errors and failover to `gemini-3.8-flash`. These retries improve resilience but cannot guarantee availability and may use additional quota. If `.env` already has an older `GEMINI_MODEL`, update that line too; values in `.env` override code defaults.

Provider outcomes are printed and saved under `providers` in `results/demo_results.json`:

- `status: "success"` with `used: "tabpfn"` or `used: "gemini"` means the remote call returned a usable result.
- `status: "fallback"` means the requested provider could not be used; `reason` names the issue without including credentials.
- `status: "local"` with `used: "local_template"` means the deterministic local implementation was selected.

For a TabPFN-only demo, expect `providers.forecast.used` to be `"tabpfn"` and `status` to be `"success"`; `"local_fallback"` means it fell back, and the `reason` gives the cause. With the default provider settings, the command does not call a hosted provider. Set `FORECAST_PROVIDER=tabpfn` and/or `BRIEF_PROVIDER=gemini` in `.env`, or pass the CLI flags above. The keys are not printed or written to result files.

## What leaves the machine

The project is intentionally honest about privacy and data flow:

- Telegram: messages pass through Telegram's servers when the bot is used in production.
- Tinker: notes may be sent for hosted inference if a Tinker account is configured and a fine-tune or sampling job is triggered.
- Prior Labs / TabPFN: when selected in the synthetic demo, the cloud client receives synthetic numeric/context feature rows and synthetic target labels. This is not the Telegram cafe-data path.
- Google AI Studio / Gemini: the local template path sends nothing; if Gemini is selected, the structured prep summary is sent to generate the brief, including when `/prep` is used in Telegram.
- ElevenLabs: voice text is sent to the voice provider when the optional voice path is enabled.
- Open-Meteo: weather requests are sent to the public weather API when a live weather service is used.

This project is not offline or fully private. It is a local-first prototype with optional cloud services.

## Accounts and keys

Create a local `.env` file from `.env.example` and fill in the values you want to use.

- Tinker: required only for a hosted fine-tuning or inference run.
- Prior Labs / TabPFN: use a token at `https://platform.priorlabs.ai/account/api-keys`; install the optional client with `python -m pip install -e ".[tabpfn]"`.
- Google AI Studio: use the API key from the AI Studio dashboard.
- Telegram: generate a bot token via BotFather; allowlisted private chat IDs are required before menu or sales data can be accessed.
- ElevenLabs: add a key only if you want the optional voice brief step.

Provider selection is separate for forecasting and briefing: use `FORECAST_PROVIDER=tabpfn` and/or `BRIEF_PROVIDER=gemini`. A provider must be explicitly selected; having a key alone does not make the CLI send requests.

## Synthetic data and honesty

The forecasting demo is built on synthetic data. Synthetic results are clearly labeled and are not real-world business results. The Telegram bot can store user-entered cafe menu and sales records locally, but its first prep calculation is a simple recent average, not a trained or validated forecasting model.

Real public datasets are not used in this first version, because the brief requires a build that is fast and testable across the full workflow with known true demand and sell-outs.

## How GitHub Copilot was used

GitHub Copilot was used to scaffold the project structure, generate the initial module layout, and iterate on the demo pipeline, tests, and README. The project intentionally keeps the data, provider interfaces, and output checks explicit so the code remains understandable and editable.

## Current limitations

The Telegram bot uses local long polling and must be running to respond; it is not deployed as an always-on service. Sales rows cannot currently be edited or replaced after saving. The optional voice step is stubbed, and TabPFN is currently connected only to the synthetic demo rather than real Telegram sales.

## Tests

```bash
python -m unittest discover -s tests -v
```

## What I would do next

- Replace the synthetic generator with a real public dataset for forecast benchmarking.
- Add a true Tinker fine-tune and compare the hand-written note set against the base extractor.
- Benchmark a forecast model for actual cafe sales and, if it performs well, connect it to Telegram's `/prep` flow.
- Add editing/correction for previously saved sales entries.
- Replace the recent-average prep forecast for real cafe records with a measured model using sufficient actual history.
- Deploy the bot with an always-on polling or webhook setup if continuous availability is needed.
- Add a voice flow with ElevenLabs only if time allows.

## License

This project is released under the MIT license.
