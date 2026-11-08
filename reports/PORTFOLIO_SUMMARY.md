# Model comparison summary

## Objective

Evaluate whether short-horizon signals in Kalshi KXBTC15M markets retain positive expected value after the contract
price, fees, slippage, execution delay, and uncertainty are included.

This is a portfolio summary of frozen historical studies. It is not a claim about current performance.

## Data and evaluation design

- Market: 15-minute Bitcoin event contracts.
- Outcome: official YES/NO settlement only.
- Inputs: 15-second market snapshots and CF Benchmarks BRTI observations when available.
- Split: chronological development and later validation periods, with complete markets kept in one split.
- Execution scenarios: quoted ask, ask plus $0.01 slippage, delayed fill, larger slippage, and limited quantity.
- Metrics: trade count, win rate, fee-adjusted break-even rate, net P&L, ROI, bootstrap interval, drawdown, and
  sensitivity to delay.

The principal comparison used six development days and three validation days with BRTI coverage. This is enough to
demonstrate the workflow, but not enough to establish a durable market edge.

## Baseline results

Project fill assumption: quoted ask plus $0.01 slippage, five contracts, hold to settlement.

| Strategy | Development ROI | Validation ROI | Validation trades | Result |
|---|---:|---:|---:|---|
| 95-cent force | -0.95% | -1.96% | 249 | High win rate remained below break-even |
| Price threshold | +1.18% | +0.87% | 249 | Small positive result; negative under delayed execution |
| Momentum v1 | -1.05% | -0.57% | 245 | No measurable edge after costs |
| Direction v1 | -3.97% | -3.17% | 249 | Raw BTC direction was insufficient |

The main lesson is that a 94–95% win rate can still lose money when contracts cost approximately 94–96 cents and
fees are added.

## Candidate rules

| Candidate | Development ROI | Validation ROI | Delay sensitivity | Interpretation |
|---|---:|---:|---|---|
| C1: short-window, low-price stable entry | +3.5% | -8.8% | Severe | Clear development overfit |
| C2: distance, non-negative move, stable entry | +8.9% | +6.5% | Falls to +2.7%, then negative with larger slippage | Promising but imprecise and low coverage |
| C3: time-adjusted distance `z >= 1.5` | +1.3% | +2.9% | Approximately flat under larger slippage | Most consistent family, still not significant |
| Model-probability edge | Large apparent historical ROI | Large apparent historical ROI | Negative when a 15-second delay is imposed | Likely stale-quote or adverse-selection effect |

C3 was selected as the best paper-test hypothesis because its neighboring thresholds behaved in the same direction
and its drawdown was smaller. Its confidence interval still included zero and one additional loss could erase much
of the apparent gain.

## Momentum failure analysis

The momentum audit connected live fills to the latest available pre-entry snapshot. The repeated failure pattern
was not simply “momentum stopped working.” The contract price often required a higher probability than the
time-adjusted BTC distance justified.

Key observations from the frozen live sample:

- small wins were offset by losses of nearly the full contract cost;
- most losses occurred at low or moderate time-adjusted distance;
- higher position size amplified the drawdown but did not cause the signal error;
- some fills were inconsistent with the expected trigger price and could not be resolved without decision logs;
- unfilled signals appeared stronger than filled signals, which is consistent with adverse selection but was not
  statistically established.

## Analog k-NN artifact

The analog pipeline represents each market near four minutes before close using:

```text
z, seconds-to-close, d2, d4, d8, d12, d20
```

It standardizes the features and uses inverse-distance weighting over the 150 nearest settled historical markets.
The generated artifact contains 913 training markets from the locally available BRTI period. This confirms the data
and production-loading pipeline, not predictive performance. A credible portfolio result requires a walk-forward
evaluation and forward shadow decisions that were not used during training.

## What this project demonstrates

- translating a trading idea into testable rules;
- separating actual fills from simulated replays;
- preventing market-level leakage with chronological splits;
- treating execution assumptions as part of the model;
- auditing calibration instead of reporting accuracy alone;
- documenting negative and inconclusive results;
- building reproducible model artifacts with data-quality reports.

## Next experiment

Run the fixed C3 and analog specifications in shadow mode for at least 30–60 independent days. Record every signal,
skip, quote timestamp, depth, latency, fill, fee, and official settlement. Compare them with an unchanged baseline
and publish the pre-registered acceptance criteria before examining results.

## Detailed evidence

- [Full strategy analysis](KALSHI_STRATEGY_ANALYSIS.md)
- [Momentum loss analysis](MOMENTUM_V2_ANALYSIS.md)
- [Paper experiment plan](KALSHI_EXPERIMENT_PLAN.md)
- [Analog data validation](../outputs/analog_4min_v1/DATA_VALIDATION.md)
