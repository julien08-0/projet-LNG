# data/terminals.py
# List of LNG terminals with their physical characteristics.
# Source: GIIGNL Annual Report 2023, public terminal specifications.

TERMINALS = [
    {
        "id":                    "RAS-LAFFAN",
        "name":                  "Ras Laffan LNG Terminal",
        "type":                  "loading",
        "country":               "QA",
        "lat":                   25.90,
        "lon":                   51.55,
        "max_draft_m":           14.0,
        "berth_count":           14,
        "avg_turnaround_hours":  24.0,
    },
    {
        "id":                    "SABINE-PASS",
        "name":                  "Sabine Pass LNG Terminal",
        "type":                  "loading",
        "country":               "US",
        "lat":                   29.73,
        "lon":                  -93.87,
        "max_draft_m":           12.5,
        "berth_count":           6,
        "avg_turnaround_hours":  30.0,
    },
    {
        "id":                    "FUTTSU",
        "name":                  "Futtsu LNG Terminal",
        "type":                  "discharge",
        "country":               "JP",
        "lat":                   35.31,
        "lon":                  139.84,
        "max_draft_m":           12.5,
        "berth_count":           3,
        "avg_turnaround_hours":  24.0,
    },
    {
        "id":                    "ZEEBRUGGE",
        "name":                  "Zeebrugge LNG Terminal",
        "type":                  "discharge",
        "country":               "BE",
        "lat":                   51.33,
        "lon":                    3.20,
        "max_draft_m":           12.0,
        "berth_count":           2,
        "avg_turnaround_hours":  24.0,
    },
    {
        "id":                    "GATE-ROTTERDAM",
        "name":                  "Gate Terminal Rotterdam",
        "type":                  "discharge",
        "country":               "NL",
        "lat":                   51.95,
        "lon":                    4.05,
        "max_draft_m":           12.0,
        "berth_count":           3,
        "avg_turnaround_hours":  24.0,
    },
    {
        "id":                    "AL-ZOUR",
        "name":                  "Al Zour LNG Terminal",
        "type":                  "discharge",
        "country":               "KW",
        "lat":                   28.75,
        "lon":                   48.20,
        "max_draft_m":           12.5,
        "berth_count":           4,
        "avg_turnaround_hours":  24.0,
    },
]


if __name__ == "__main__":
    print("=== terminals.py ===")
    print(f"  {len(TERMINALS)} terminals loaded\n")
    for t in TERMINALS:
        print(f"  [{t['id']:<16}] {t['name']:<35} type={t['type']:<10} "
              f"draft<={t['max_draft_m']}m  berths={t['berth_count']}")
    print("\nOK")
