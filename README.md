# LNG Ops Tool

An LNG shipping & trading desk simulator: it manages a small fleet of LNG carriers end to end — which vessel loads which cargo, where it sails, and where it discharges — and answers the question every scheduling/optimization desk is built around: **given a cargo and a fleet, what is the most profitable decision, and why?**

Under the hood it's an optimization engine (MILP) sitting on top of a physical and market model — boil-off, laycans, routing, chokepoints, freight/canal costs, live-ish market prices — surfaced through an interactive Streamlit dashboard so every decision can be inspected and explained, not just computed.

**Live demo:** [project-lng.streamlit.app](https://project-lng.streamlit.app/)

## How decisions get made

This is the core of the project — everything else (map, KPIs, tables) is a window into these decisions.

- **Vessel ↔ cargo assignment** — a MILP (PuLP/CBC) chooses which vessel loads which cargo, maximizing total fleet net margin, subject to hard constraints: cargo capacity, draft at both load and discharge terminals, laycan compliance, and *reachability* (can the vessel actually reach the loading terminal before laycan end, given the real routed ballast distance — not straight-line distance). Infeasible pairs are pruned before the solver ever sees them.
- **Destination optimization** — for cargoes without a fixed discharge terminal (flexible DES), every candidate destination is priced out: revenue at that market minus transport, boil-off loss, canal tolls, and demurrage risk, using `core/pnl.py`. The engine picks the max-net-margin destination and prints the reasoning in plain text (`format_decision_text`), so every routing choice is auditable, not a black box.
- **Routing & rerouting** — routes are computed dynamically (great-circle + real waypoints), not looked up from a static table. Closing a chokepoint (Suez, Hormuz, Panama, ...) forces the router to re-derive the alternate path (e.g. Cape of Good Hope, Cape Horn) and re-price every affected voyage live.
- **Spot trading** — each day, every idle vessel is evaluated against all loading×discharge combinations across three regional markets (JKM/TTF/Henry Hub, mean-reverting and partially correlated); it's dispatched to the most profitable route only if expected margin clears a minimum threshold — with expected vs. realized P&L tracked separately, so a trade that looked good on paper can still land as a loss once the market moves.
- **Disruption impact** — vessel delay, terminal outage, or chokepoint closure scenarios are run against the same optimizer to produce a baseline-vs-disrupted dollar delta, not just a qualitative "this is bad."

## Everything else (the dashboard around it)

- **Fleet Map** — animated 45-day map (Plotly): vessels move along the routed path at their actual speed, tank level drops with boil-off, chokepoint closures reroute live
- **KPI Dashboard** — fleet utilization, boil-off (BOG) loss, bunker savings, net margin, 30-day Gantt of vessel assignments
- **Fleet Management** — add vessels to the fleet for the current session (in-memory only)
- **Train Performance (upstream)** — liquefaction train model (Ras Laffan, Qatar) feeding the cargo pipeline: thermal derating, load-factor ramp, optimized maintenance scheduling, unplanned outages

## Technical data & pricing assumptions

Every number the optimizer trades on is a real-world LNG shipping/trading concept, kept in one place (`config.py`, no magic numbers scattered in the code).

**Market prices & freight economics**

| Benchmark | Value | How it's built |
|---|---|---|
| TTF (Europe spot) | $10.80/mmBtu | Fallback anchor; live FX via frankfurter.app |
| JKM (Asia spot) | $11.50/mmBtu | `TTF + $0.70` spread — Asia normally trades over Europe |
| Henry Hub (US) | $2.40/mmBtu | Raw US feedgas price — **not** a delivered LNG price |
| US FOB cargo cost | `115% × HH + $3.00/mmBtu` | Standard Cheniere-style SPA indexation: HH is wellhead gas, so the liquefaction toll + margin has to be added before it's comparable to a landed cargo — using raw HH as a buy price would create a fake arbitrage every run |
| Freight (charter cost) | $60k–95k/day by class (Q-Max highest, STEAM lowest) | Charged **per day of actual voyage**, not a flat fee — a Gulf→Asia leg costs more in freight than Gulf→Europe simply because it takes longer, on top of the price spread itself |
| Canal tolls | Suez $600k / 16h · Panama $350k / 24h | Added to a route only when the computed path actually transits that canal |
| Demurrage | $80k–150k/day by class | Charged on hours beyond the 24h free laytime at load and discharge, when laycan/berth timing slips |

Net margin for a given (cargo, vessel, destination) = revenue at the destination marker − freight (rate × voyage days) − boil-off loss − canal tolls − demurrage risk. That's the number the MILP and the destination optimizer both maximize.

Spot prices layer a bounded random walk on top of these anchors: 2–5%/day volatility by benchmark, ~3%/day mean-reversion pull back to anchor (Ornstein–Uhlenbeck style — commodity prices don't drift forever), and a 70% correlation between JKM and TTF (they arbitrage each other via redirectable floating cargoes; Henry Hub is a decoupled domestic US market).

**Vessel physical parameters** (by class)

| Class | Capacity | Boil-off rate | Heel (min. retained) | Fuel consumption | Max draft | Demurrage |
|---|---|---|---|---|---|---|
| Q-Max | ~265,000 m³ | 0.150%/day | 3.0% of capacity | 700 mmBtu/day | 12.5 m | $150k/day |
| Q-Flex | ~210–216,000 m³ | 0.150%/day | 3.0% of capacity | 650 mmBtu/day | 12.0 m | $120k/day |
| TFDE | ~155–160,000 m³ | 0.100%/day (re-liquefaction capable) | 4.0% of capacity | 580 mmBtu/day | 11.5 m | $95k/day |
| STEAM (older) | — | 0.150%/day | 5.0% of capacity | 750 mmBtu/day | 11.5 m | $80k/day |

- **Boil-off (BOG)** — LNG constantly vaporizes in the tank; modeled as *exponential* decay, `V(t) = V0 × e^(−k·t)` (the gas lost on a given day is proportional to what's left that day, not to the original load) — a flat linear rate would overstate losses on long transits. Rate is adjusted for ambient temperature and sea state.
- **Heel** — the minimum volume that must *always* stay in the tank, never delivered commercially: it keeps the containment system cryogenically cooled so the next cargo doesn't boil off on contact with a warm tank. It erodes like any other LNG during a ballast (empty) leg, so a long ballast run means reserving more heel at departure to still have enough left on arrival.
- **1 m³ LNG ≈ 21.0 mmBtu** — the single conversion factor used everywhere volumes cross between physical (m³) and commercial (mmBtu) units.
- **Two speeds per vessel** — ballast (empty) is a little faster than laden (loaded), since an empty hull rides higher and meets less resistance; routing and reachability checks use whichever leg they're computing.

## Architecture

The codebase is organized in strict layers — a lower layer never depends on a higher one (`config → data → core → ui`):

- `config.py` — all physical and market parameters (no logic)
- `app.py` — Streamlit entry point / page router
- `data/` — static fleet data: terminals, vessels, cargoes, maritime waypoints
- `core/` — business logic: physics (boil-off, ETA, demurrage), constraints, routing, MILP optimizer, disruption, P&L, market prices, spot trading
- `ui/` — Streamlit pages, wired to `core/` only
- `train_ops/` — self-contained upstream package (its own config/data/core/ui layers), connected to the rest of the app only through `app.py`

Each `core/` module ends with a `if __name__ == "__main__":` self-test block that proves it runs correctly on its own.

## Tech stack

Python · Streamlit · Plotly · pandas · PuLP (MILP solver) · Requests

## Run locally

```
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
streamlit run app.py
```

By default, all market prices (JKM, TTF, Henry Hub, Brent, FX) fall back to static values in `config.py`, so the app runs fully offline and deterministically. Live sources (Brent via yfinance, FX via frankfurter.app, Henry Hub via the EIA API) are optional — see `CONTEXT.md` for details.

## Project context

Portfolio project built while completing an engineering degree at CentraleSupélec (graduating August 2027), alongside a work-study program (alternance) in LNG electrical engineering at Technip Energies.
