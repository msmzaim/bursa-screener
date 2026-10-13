# Bursa Research Desk

A complete Streamlit replacement for a Bursa screener, stock analysis page, and manual portfolio monitor. This is a research prototype: no trading edge or profitability has been established. It does not place orders.

## Start on your Mac

Install Python 3.11 or newer, then open Terminal in this project folder and run:

```sh
sh run.sh
```

The script creates a local virtual environment, installs requirements, and starts Streamlit. Your browser should open at http://localhost:8501. Stop it with Control-C.

Alternatively:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

For Windows PowerShell, use `py -m venv .venv` and `.venv\Scripts\Activate.ps1` instead of the first two lines.

Turn on **Offline demo — synthetic prices** to try every screen without Yahoo access. Demo results are fictional and clearly labelled. Turn it off for provider data, then run a new scan.

## Project files

- `app.py`: all Streamlit screens and user controls.
- `engine.py`: indicator calculations, technical rules, FA checks, tick rounding and risk sizing.
- `data.py`: cached Yahoo requests and synthetic demo data.
- `tickers.csv`: 849 Main/ACE securities extracted from the supplied SC list dated 29 May 2026.
- `shariah_list.csv`: identical list for compatibility with your original app.
- `shariah_reference.csv`: all 886 entries including 37 LEAP securities.
- `SHARIAH_SOURCE.md`: source-page mapping and reconciliation.
- `install_update.py`: backup-and-copy installer for an existing GitHub project.
- `requirements.txt`: runtime dependencies.
- `tests/`: calculation and offline Streamlit journey tests.
- `run.sh`: Mac/Linux launcher.
- `.streamlit/config.toml`: theme and telemetry preference.

## Add your Bursa universe

Edit `tickers.csv` or upload a CSV in the sidebar. Read all codes as text to retain leading zeros. `ticker`, `code`, or `symbol` is required; `name` is optional.

```csv
ticker,name,shariah_status,shariah_as_of
5347,Tenaga Nasional,,
0166,Inari Amertron,,
```

The default universe now comes from the **SC Malaysia SAC list dated 29 May 2026**, printed pages 20–38 (PDF pages 21–39). All 886 unique securities reconcile with all 12 sector totals in the source summary. The app scans the 642 Main + 207 ACE securities; 37 LEAP entries are retained in `shariah_reference.csv` but excluded from this four-digit-code app. This is a dated snapshot; later classification changes are not checked automatically.

Stock analysis checks membership against the bundled SC reference even if you upload a different universe. An absent stock is marked unverified, not automatically non-compliant. Consult the current [SC Malaysia lists](https://www.sc.com.my/development/islamic-capital-market/list-of-shariah-compliant-securities). Do not upload ETFs, warrants or other instruments outside this app's scope.

The scanner processes the first N rows. Start with 30; set N to 849 for the entire bundled Main/ACE universe. A full scan makes many provider requests and can be slow or throttled. Errors are visible.

## How the screening works

Both the market screen and stock analysis call the same engine.

All technical gates must pass:

1. At least 220 completed observations, latest no older than seven calendar days.
2. Price and prior 20-session average traded value meet the sidebar minimums.
3. Close > SMA50 > SMA200, with SMA200 rising over 20 sessions.
4. Wilder RSI14 is between 40 and the configured maximum.
5. In the previous five sessions, at least one bullish candle has volume at least the configured multiple of its **prior** 20-session volume mean, range at least 1.2 times its prior range mean, and a close in the top 35% of its range.
6. The newest session closes below the previous close, has lower-than-baseline volume and a narrower-than-baseline range, closes in its upper half, and holds the most recent qualifying impulse's low.
7. No reported stock split in the last 200 observations.

A separate label says whether the impulse closed above its prior 20-session high. That label is context, not a gate. This is a Wyckoff-inspired continuation hypothesis; it does not identify complete Wyckoff phases or institutional activity.

Strict FA requires **all five** conditions: positive trailing P/E ≤25, ROE ≥10%, positive operating cash flow, debt/equity between 0% and 100%, and positive revenue growth. Unknown metrics never pass. Financial Services, Real Estate and known non-equity types require a separate model, so they do not pass strict mode. These are configurable-code research defaults, not a valuation model or recommendations. Turn strict mode off to investigate technical candidates with incomplete FA, while still seeing their FA status.

## Prices, sizing, and portfolio records

- Today's Malaysia-date daily candle is always excluded, even after close. It becomes eligible on the next calendar date. This is deliberately conservative and is not an exchange-calendar implementation.
- Requests explicitly use unadjusted OHLC; reported splits block candidates. Dividends and other corporate actions can affect signals. This is not total-return history.
- Wilder smoothing is arithmetic-seeded. Rolling volume/range baselines exclude the candle under examination.
- The last close is a **planning reference**, not a guaranteed next entry price.
- Sizing selects 100-share board lots under both the allocation cap and estimated risk budget. It includes user-entered fee/slippage estimates. Defaults are examples, not current Rakuten fees. Stops can gap and actual losses can exceed the estimate.
- Ordinary-equity ticks used are RM0.005 below RM1, RM0.01 below RM10, RM0.02 below RM100, and RM0.10 thereafter. Special instruments have different conventions.
- A portfolio entry is an actual position you type in. It is not created by a screen result or an executed order.
- Portfolio data is held in the browser's Streamlit session. Export JSON for backup and import to restore. There is no durable cloud database. Import replaces the current journal after validating the whole file.
- P&L is gross of costs, distributions and corporate actions. Daily high/low checks apply only to the latest completed session, which may be before entry; they are not fill confirmations or continuous alerts.
- Data failures remain visible. A missing price is not converted into zero P&L.

## Push to a new GitHub repository

Create an **empty** repository named `bursa-research` on GitHub. Do not initialise it with a README. From this project folder, run the following after replacing `YOUR_USERNAME`:

```sh
git init -b main
git add app.py engine.py data.py requirements.txt tickers.csv shariah_list.csv shariah_reference.csv SHARIAH_SOURCE.md README.md run.sh install_update.py tests .gitignore .streamlit/config.toml
git commit -m "Add Bursa research screener and portfolio journal"
git remote add origin https://github.com/YOUR_USERNAME/bursa-research.git
git push -u origin main
```

GitHub may ask you to authenticate. Use your normal credential manager or GitHub CLI; do not paste tokens into source files. Portfolio exports, environment files and Streamlit secrets are ignored. Review your CSV before making the repository public.

For an existing repository, copy the project files into a separate branch, review changes, and commit there. Do not blindly rerun repository creation commands against an existing app.

## Deploy on Streamlit Community Cloud

1. Push these files to GitHub.
2. Sign in at https://share.streamlit.io and choose **Create app**.
3. Select your repository, branch `main`, and entrypoint `app.py`.
4. Select Python 3.12 in advanced settings, then deploy.
5. Test the offline demo first, then a single real stock before a larger scan.

No API secret is required for these Yahoo requests. Dependency versions reflect the environment used for the included offline tests; cloud deployment and live Yahoo retrieval have not been verified here. See the official [deployment instructions](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## Tests

From the project folder with dependencies installed:

```sh
python -m unittest discover -s tests -v
```

Fourteen tests cover Wilder seeding, flat/uptrend RSI, causal baselines, excluding the current date, insufficient/stale/split data, a positive pullback and a false rising-day setup, incomplete FA, sector restrictions, cash/risk limits, tick boundaries, portfolio validation, the offline Streamlit screen/analyse/add/remove journey, and reconciliation of all 886 source entries and 12 sector counts.

Passing these checks means the tested code paths work. It does **not** validate returns. No backtest or win-rate claim is included. Before investment use, add point-in-time historical statements, historical universe membership including delistings, next-session fills, costs, walk-forward testing and paper trading.

## References

- [yfinance API and explicit price adjustment options](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [Streamlit data caching](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data)
- [Wyckoff method tutorial](https://chartschool.stockcharts.com/table-of-contents/market-analysis/wyckoff-analysis-articles/the-wyckoff-method-a-tutorial)
- [Ordinary-share tick bands and instrument exceptions, OCBC Securities](https://www.iocbc.com/help-and-support/market-information/pan-asia-pacific.page)
- [RSI interpretation, Fidelity](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI)

Yahoo data access, completeness and terms can change. Check the provider's applicable terms before redistributing data or running a public/commercial service.

## Easy update of your existing app

Open Terminal in your existing GitHub project folder (the folder containing your current `app.py`). Run the `install_update.py` file from this release using its full path. The installer checks the destination, backs up existing files outside Git, and copies the replacement app and source lists. It does not commit or push. It preserves your Streamlit configuration and existing README, and adds this guide as `SETUP_BURSA.md`.

After installing:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s bursa_tests -v
python -m streamlit run app.py
```

After checking the app, stop Streamlit with Control-C and publish:

```sh
git add app.py engine.py data.py requirements.txt tickers.csv shariah_list.csv shariah_reference.csv SHARIAH_SOURCE.md SETUP_BURSA.md bursa_tests .gitignore
git commit -m "Update Bursa app and SC May 2026 Shariah list"
git push
```

Push to the branch already connected to your Streamlit deployment. No new repository is needed.
