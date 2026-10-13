# Bursa Research Desk — research edition

An evidence-led Streamlit workflow for Bursa screening, company research, conditional trade plans, portfolio exposure and technical strategy testing. The bundled universe remains the supplied SC Malaysia SAC list dated 29 May 2026: 849 Main/ACE stocks plus a separate full 886-entry reference.

This upgrade improves the research process. It does not certify senior-analyst judgement, investment suitability, a complete Wyckoff model or profitability.

## Update your existing project — copy and paste

Open Terminal. If that window is running Streamlit, press Control-C first.

```sh
cd "/Users/muhdsalman/bursa-screener"
python3 "/Users/muhdsalman/Documents/Codex/2026-10-13/is-x20/outputs/bursa-research/install_update.py"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The installer saves the replaced files in a temporary backup folder outside Git and prints its location. It preserves your existing README and Streamlit settings, saves this guide as `SETUP_BURSA.md`, and copies the tests to `bursa_tests`. It does not commit or push. The source files are also available in the release ZIP.

If you are starting from the extracted ZIP instead, open Terminal in that folder and run `sh run.sh` (Python 3.11+; Python 3.12 is recommended for cloud deployment).

## Try the new workflow

1. Turn **Offline demo** on to test synthetic data, or leave it off for Yahoo data.
2. In **Market screener**, start with 30 stocks. Optional gates require five snapshot FA checks, supportive KLCI and positive 63-session relative strength. This is a shortlist, not annual-statement approval.
3. In **Stock analysis**, choose a stock and click **Analyse stock**. Select up to six sector peers and click **Build research report**.
4. Read the market/peer and annual-statement evidence. Enter your sourced business thesis and record your upcoming-event review. Review the conditional entry, structural stop, resistance-capped target and portfolio constraints. Download the report if needed.
5. In **Historical testing**, run a five-year technical-only test. Read the development, chronological holdout and doubled-cost results. Download the holdout trades and test assumptions.
6. Keep actual holdings in **Portfolio journal**, and export JSON backups. The report uses those holdings to check exposure. Session state is not durable cloud storage.

## Publish after checking locally

Press Control-C to stop Streamlit, then:

```sh
git add app.py engine.py data.py research.py research_ui.py backtest.py requirements.txt tickers.csv shariah_list.csv shariah_reference.csv SHARIAH_SOURCE.md SETUP_BURSA.md bursa_tests .gitignore
git commit -m "Add analyst research workflow and technical backtesting"
git push
```

Use the branch linked to your existing Streamlit deployment. The entrypoint remains `app.py`. No additional API key is needed. For a new deployment, see [Streamlit's official guide](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).

## What changed

| Feature | Evidence and interpretation |
| --- | --- |
| Market regime | KLCI close/SMA50/SMA200 and long-term slope; supportive, mixed or defensive. KLCI is a price-index reference, not a Shariah index. |
| Relative strength | Stock and index returns over 21, 63 and 126 shared sessions; difference in percentage points, not risk-adjusted alpha. Latest dates must match. |
| Sector sample | User-selected peers from the SC sector, with matching-date trend checks; not a full sector index or unbiased breadth measure. |
| Peer valuation | Positive trailing P/Es with exactly matching provider industry. At least three comparable peers are required for a median; no fair-value claim follows from a discount. |
| Statement quality | Up to four annual periods, earnings consistency, revenue growth, cash conversion, free cash flow, net debt/EBITDA and interest cover. Matching fiscal-end dates are required across statements. |
| Valuation sensitivity | User-editable EPS growth and P/E multiples. Requires positive EPS and confirmed MYR quote/financial currencies. These are scenarios, not forecasts or probabilities. |
| Trade plan | Entry above completed-bar high; support/ATR invalidation; known swing resistance can cap the projected target. Trigger expiry and no-chase conditions are explicit. |
| Portfolio constraints | Cash, allocation, per-trade risk, position/sector caps, total mark-to-stop risk, volume participation and correlation warnings. |
| Research notes | User-authored thesis, source link and event review. The application does not invent catalysts or claim a complete earnings calendar. |
| Historical testing | Technical-only next-session simulation, development/holdout split, cost stress, net expectancy, equity drawdown, sample size and trade ledger. |

## Exact rules and limits

### Original shortlist

The technical engine still requires at least 220 completed sessions, price and prior traded-value thresholds, Close > SMA50 > SMA200, rising SMA200, RSI 40 to the configured maximum, and a bullish impulse in the preceding five sessions. The impulse needs volume expansion, a wide range and a strong close. The latest bar must actually pull back, trade more quietly in a narrower range, close in its upper half and hold the impulse low. This is Wyckoff-inspired continuation research; it does not classify full accumulation/distribution phases.

The optional snapshot FA filter requires positive trailing P/E ≤25, ROE ≥10%, positive operating cash flow, debt/equity 0–100%, and positive revenue growth. Missing data cannot pass. Financial Services and Real Estate require sector-specific models.

### Annual-statement checks

Generic thresholds are visible assumptions: annual period end within 550 days, positive earnings and free cash flow, cash conversion ≥0.8×, net debt/EBITDA ≤3×, interest cover ≥3×, three consecutive profitable years and positive annual revenue growth. Zero interest does not create an infinite coverage pass; coverage remains unassessed. Negative earnings cannot produce a misleading positive cash-conversion ratio. Statements are matched by exact fiscal-end date. These are provider-normalized annual accounts, not a forensic audit of filings or a substitute for recent quarterly results.

### Conditional trade plan

- Trigger: one valid ordinary-share tick above the latest completed bar's high.
- Stop: lower of the ten-session low minus 0.25 ATR, or trigger minus configured ATR distance, floored at RM0.005 and rounded down.
- Target: chosen risk multiple, capped by the nearest confirmed historical swing-high resistance above entry. Swings need two known bars on each side; no future bars are used.
- Trigger validity: next three observed sessions. Live report expiry uses a conservative weekday count, without an exchange-holiday calendar.
- No-chase ceiling: trigger plus 0.25 ATR, rounded down.
- Historical time exit: close of the twentieth holding session if no earlier exit.
- A sizing table is not permission to trade. Unresolved technical, FA, annual-statement, market, relative-strength or user-event checks keep the report on the watchlist. A material event within seven days requires reassessment.

### Sizing and exposure

Default research limits: 0.5% risk per trade, 20% position cap, 35% sector cap, 3% portfolio mark-to-stop risk, 1% average-volume participation and 1.5× minimum net reward/risk. All are adjustable assumptions, not personalised recommendations. Whole 100-share lots must also fit the cash/allocation cap and estimated fees/slippage. Existing positions in the same stock block automatic additional sizing.

Available cash is the supplied equity less marked holdings. Risk-to-stop is current marked value less estimated stop proceeds, including exit costs; it is not a guaranteed maximum loss. Missing/stale prices, missing sectors or unreconciled reported splits in holdings block sizing. Correlations use at least 60 and up to 120 common daily returns; ≥0.75 produces a warning, not an automatic allocation model. There is no account connection, broker cash verification or portfolio optimiser.

### Historical simulation

The backtest deliberately tests only the technical entry rules and structural execution plan. Current FA, statement quality, peers, market gates, user thesis and event notes are not applied to past dates. It is not a test of the full current research verdict.

After 220-bar warm-up, the first 70% of eligible observations forms the development window and the last 30% the chronological holdout. Each window starts with the same cash and no carried position, but indicators can use earlier history. No parameter fitting is automated. Repeatedly inspecting and tuning on the holdout destroys its independence; this implementation is not a rolling optimisation/walk-forward system.

Signals use data available at the close. Entries can first occur on the next bar, only when the trigger is reached within three observations, inside the no-chase ceiling. The simulation allows one long position, no leverage and 100-share lots. Capacity uses previously available volume. A gap through the stop exits at the opening price less slippage. If daily OHLC touches stop and target, the stop is assumed first, including entry-day ambiguity. Targets receive no favourable gap improvement. Stops and targets use estimated slippage and fees; the window's final bar is liquidated. Fees and slippage double in a separate stress run.

Reported dividends are credited only for positions carried into the ex-date, with immediate cash availability as a simplifying assumption. Any reported stock split blocks the historical test. Rights issues, other missing corporate actions, suspensions and daily-bar execution ambiguity remain limitations. Equity drawdown includes daily marked holdings. P&L is net of modelled costs; no-trade results are shown without fabricated win rates. Fewer than 30 trades is explicitly labelled a small sample; 30 or more does not establish robustness.

The KLCI comparison is a fully invested price-index return over the displayed dates. It excludes dividends and is not exposure/risk matched to the strategy. This simulator uses a selected existing stock; survivorship, universe-selection and data-quality issues prevent claiming a whole-market edge. Historical Shariah compliance is not inferred from the May 2026 list.

## Data policy

Daily Yahoo bars are not live quotes. Today's MYT candle is always omitted, even after close. RSI/ATR use arithmetic-seeded Wilder smoothing; rolling volume/range baselines exclude the evaluated candle. Unadjusted OHLC is requested explicitly. A recent reported split blocks a technical candidate. Corporate-action coverage is not guaranteed; price comparisons are not total returns. Prices and company data are cached separately, with visible dates and provider errors. Annual statements may be missing for some Bursa stocks.

The source universe is unchanged: 642 Main, 207 ACE and 37 LEAP entries, matching 886 unique codes and all 12 sector totals. Default `tickers.csv` and compatibility `shariah_list.csv` include the 849 Main/ACE names. `shariah_reference.csv` retains all entries and source pages. Classification is explicitly dated 29 May 2026, not a real-time compliance assertion. See `SHARIAH_SOURCE.md`.

## Tests and verification

In the installed project:

```sh
python -m unittest discover -s bursa_tests -v
```

In the release folder, use `tests` instead of `bursa_tests`. Twenty-eight tests cover the original engine and universe reconciliation plus market date alignment, financial-period matching, incomplete statements, peer comparability, currency guards, structural plans, portfolio blocks, next-session execution, both-hit ordering, gap stops, dividend entitlement, no-chase gaps, costs, holdout separation, corporate-action blocks and the complete offline Streamlit workflow. The copied installation is also tested in a temporary Git project.

Live Yahoo availability and the upgraded cloud deployment have not been verified here. Passing software tests is not investment-performance validation. No historical return or win-rate claim is supplied with this release.

## Files

- `app.py`: Streamlit screens and screening controls.
- `engine.py`: base indicators, signal rules, snapshot FA and sizing.
- `data.py`: provider access and offline demo fixtures.
- `research.py`: market, statement, peer, valuation and portfolio research logic.
- `research_ui.py`: report, scenarios and historical-test presentation.
- `backtest.py`: daily-bar historical simulator.
- `tests/`: automated checks, copied to `bursa_tests/` by the installer.
- `install_update.py`: backup-and-copy upgrade, with no automatic commit/push.

## Sources for implementation conventions

- [yfinance financial-statement API](https://ranaroussi.github.io/yfinance/reference/yfinance.financials.html)
- [Yahoo KLCI symbol](https://finance.yahoo.com/quote/%5EKLSE/)
- [CFA Institute discussion of look-ahead and survivorship bias](https://www.cfainstitute.org/insights/articles/good-bad-and-ugly-of-bias-in-ai)
- [Wyckoff method tutorial](https://chartschool.stockcharts.com/table-of-contents/market-analysis/wyckoff-analysis-articles/the-wyckoff-method-a-tutorial)
- [Ordinary-equity tick bands and instrument exceptions, OCBC Securities](https://www.iocbc.com/help-and-support/market-information/pan-asia-pacific.page)

These sources describe data interfaces and research conventions; they do not validate this strategy. Check provider terms before redistributing data or running a public/commercial service. Keep portfolio exports and private research reports out of public repositories.
