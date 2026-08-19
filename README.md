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

## Technical data

- **Prices** — TTF (Europe) and JKM (Asia, = TTF + spread) as market anchors, Henry Hub for US cargoes (converted to a delivered cost via indexation + liquefaction fee, since HH is raw feedgas not LNG), plus freight (charter rate × voyage days), canal tolls, and demurrage — all by vessel class, all in `config.py`.
- **Boil-off** — LNG evaporates in transit; the tool models this loss (exponential decay) and nets it out of the cargo volume and the margin calculation.
- **Heel** — a minimum volume that must always stay in the tank (never delivered), to keep it cold enough for the next load.
- **Fleet** — 4 vessel classes (Q-Max, Q-Flex, TFDE, STEAM), each with its own capacity, speed, fuel consumption, boil-off rate, and draft.

## Everything else (the dashboard around it)

- **Fleet Map** — animated 45-day map (Plotly): vessels move along the routed path at their actual speed, tank level drops with boil-off, chokepoint closures reroute live
- **KPI Dashboard** — fleet utilization, boil-off (BOG) loss, bunker savings, net margin, 30-day Gantt of vessel assignments
- **Fleet Management** — add vessels to the fleet for the current session (in-memory only)
- **Train Performance (upstream)** — liquefaction train model (Ras Laffan, Qatar) feeding the cargo pipeline: thermal derating, load-factor ramp, optimized maintenance scheduling, unplanned outages

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
