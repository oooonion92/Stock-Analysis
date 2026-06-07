# StockCodex V1 Clean Handoff

Updated: 2026-06-03

## Current Working Repo

- Active code repo: `D:\Projects\StockCodex_v1`
- Active branch: `v1-clean`
- Remote: `git@github.com:oooonion92/Chanlun-Tool.git`
- Shared memory: `D:\OneDrive\Stock\Codex\codex_memory`
- Shared market data: `D:\OneDrive\Stock\details`

## Current Baseline

- Previous clean sandbox commit: `965c70c chore: refine sandbox ui colors and version label`
- Expected sandbox UI version label after today's update: `V10.20-0603-1715`
- Start sandbox manually with `启动缠论沙盒.bat`, then open `http://127.0.0.1:8765/`.

## Imported Offline Update

Imported from local ZIP:

```text
D:\Projects\StockCodex_v1\Chanlun-Tool-1-review-20260602.zip
```

This brought in the evening replay-review work described in OneDrive memory:

- source branch context: `v1-review-20260602`
- latest noted replay commit: `d8686f0 feat: add replay dashboard html generator`
- replay workflow files under `review_plans/`
- replay generator tools under `tools/`
- replay/deep-analysis skill bundle under `china-stock-deep-analysis-local/`

## Sandbox Update

The sandbox core files were also intentionally updated from the offline ZIP and refined in place.

Current sandbox behavior:

- app version is `V10.20-0603-1715`
- right side of the chart reserves virtual blank space for a new trading day
- selecting an existing symbol auto-syncs latest data before analysis
- symbol refresh and new-symbol sync use compact icon buttons
- symbol dropdown displays only the symbol code
- chart title shows stock name + symbol + period
- version is shown separately in the upper-right in muted text
- `底部灵敏度` and `5m 配色` controls are removed again

## Replay Methodology

- Use `review_plans/stock_trading_methodology.md` as the standing methodology for future reviews.
- Use `review_plans/replay_method_prompt.md` as the short execution checklist.
- Always separate short-term trades from trend/swing positions before applying Chanlun structure.

## Verification Done

- `chanlun_sandbox_app.py` compiles.
- `chanlun_engine_v10_21.py` compiles.
- `chanlun_v10_20_core.py` compiles.
- `tools\chanlun_replay_plan.py` compiles.
- Temporary sandbox run returned homepage and sample analyze API successfully.
- Current sandbox API returns version `V10.20-0603-1715`.
- Page HTML no longer contains visible `id="sensitivity"` or `id="theme5m"` controls.

## Safety Notes

- Do not force-push.
- ZIP archives and `_zip_import_*` temporary folders are ignored by `.gitignore`.
- If GitHub SSH is awkward on this machine, ZIP import remains a usable offline fallback.
