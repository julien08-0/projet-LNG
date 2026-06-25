"""
tests/test_physics.py
---------------------
Unit tests for core/scheduling/physics.py

Values are chosen to match realistic LNG operational scenarios.
Each test is annotated with its operational significance — a recruiter
reading these tests should understand what real-world situation is covered.
"""

import pytest
from core.scheduling.physics import (
    calculate_boiloff,
    calculate_heel_requirement,
    heel_boiloff_during_ballast,
    calculate_eta,
    check_laycan_compliance,
    calculate_demurrage,
    reconcile_cargo_volume,
    check_draft_compatibility,
    LNG_ENERGY_DENSITY_MMBTU_PER_M3,
)


# ---------------------------------------------------------------------------
# Boil-off tests
# ---------------------------------------------------------------------------

class TestBoilOff:

    def test_typical_qflex_qatar_to_japan(self):
        """
        Realistic scenario: Q-Flex loaded at Ras Laffan (Qatar) → Futtsu (Japan)
        Distance ~7,000 nm, 17-18 days at 17 knots, ambient ~30°C (Gulf + Indian Ocean)
        Typical cargo: 160,000 m³ ≈ 3,360,000 mmBtu
        """
        result = calculate_boiloff(
            cargo_volume_mmbtu=3_360_000,
            transit_days=18.0,
            vessel_class="Q-Flex",
            ambient_temp_celsius=30.0,
            sea_state_factor=1.1,  # moderate swell in Arabian Sea
        )
        # At 0.15%/day with temp adjustment, ~0.155% effective rate
        # BOG ≈ 3,360,000 × 0.00155 × 18 ≈ 93,744 mmBtu
        assert 85_000 < result.gross_bog_mmbtu < 110_000, (
            f"BOG {result.gross_bog_mmbtu:,.0f} mmBtu outside expected range for Qatar→Japan"
        )
        # Net volume should still be >95% of cargo
        assert result.volume_delivered_mmbtu > 3_200_000
        # BOG as fuel should cover engine demand (600 mmBtu/day × 18 days = 10,800)
        assert result.bog_used_as_fuel_mmbtu >= 10_000
        # Bunker saving must be positive
        assert result.bunker_cost_saving_usd > 0
        assert not result.warmup_penalty_applied

    def test_warmup_penalty_increases_bog(self):
        """
        If a vessel discharged without maintaining sufficient heel, tank walls
        partially warm up during ballast voyage. The first hours of loading
        generate excess BOG as the tank cools back down.
        """
        base = calculate_boiloff(
            cargo_volume_mmbtu=3_000_000,
            transit_days=10.0,
            vessel_class="TFDE",
            heel_was_sufficient=True,
        )
        penalised = calculate_boiloff(
            cargo_volume_mmbtu=3_000_000,
            transit_days=10.0,
            vessel_class="TFDE",
            heel_was_sufficient=False,
        )
        assert penalised.gross_bog_mmbtu > base.gross_bog_mmbtu
        assert penalised.warmup_penalty_applied
        assert not base.warmup_penalty_applied

    def test_tfde_lower_bog_than_steam(self):
        """
        TFDE vessels have superior insulation and re-liquefaction capability.
        They should show lower net BOG loss than older STEAM turbine vessels
        on identical routes.
        """
        params = dict(cargo_volume_mmbtu=3_000_000, transit_days=20.0, ambient_temp_celsius=25.0)
        tfde = calculate_boiloff(**params, vessel_class="TFDE")
        steam = calculate_boiloff(**params, vessel_class="STEAM")
        assert tfde.gross_bog_mmbtu < steam.gross_bog_mmbtu

    def test_hot_ambient_increases_bog(self):
        """
        Qatar summer (45°C) vs Qatar winter (20°C).
        Heat ingress through insulation is proportional to temperature differential
        (T_ambient - T_LNG). Higher ambient = more heat in = more BOG.
        """
        summer = calculate_boiloff(
            cargo_volume_mmbtu=3_200_000, transit_days=5.0,
            vessel_class="Q-Max", ambient_temp_celsius=45.0,
        )
        winter = calculate_boiloff(
            cargo_volume_mmbtu=3_200_000, transit_days=5.0,
            vessel_class="Q-Max", ambient_temp_celsius=20.0,
        )
        assert summer.gross_bog_mmbtu > winter.gross_bog_mmbtu

    def test_bog_never_exceeds_cargo(self):
        """
        Sanity check: total BOG cannot exceed the cargo loaded.
        Even in extreme conditions (very long voyage, high ambient) the formula
        must not produce a negative delivered volume.
        """
        result = calculate_boiloff(
            cargo_volume_mmbtu=500_000,
            transit_days=90.0,  # unrealistically long
            vessel_class="STEAM",
            ambient_temp_celsius=50.0,
            sea_state_factor=1.5,
        )
        assert result.gross_bog_mmbtu <= 500_000
        assert result.volume_delivered_mmbtu >= 0.0


# ---------------------------------------------------------------------------
# Heel tests
# ---------------------------------------------------------------------------

class TestHeel:

    def test_qmax_requires_larger_absolute_heel(self):
        """
        Q-Max at 265,000 m³ capacity × 3% = 7,950 m³ minimum heel.
        This is critical for Ras Laffan-based fleets — Q-Max cannot operate
        on routes that don't allow enough time to reconstitute heel.
        """
        result = calculate_heel_requirement(
            vessel_capacity_m3=265_000,
            vessel_class="Q-Max",
        )
        expected_m3 = 265_000 * 0.03
        assert abs(result.required_heel_m3 - expected_m3) < 1.0
        assert result.is_sufficient  # default: actual = required

    def test_insufficient_heel_flags_penalty(self):
        """
        If a vessel retains only 2% when 4% is required (TFDE class),
        the next loading will incur the warm-up BOG penalty.
        """
        result = calculate_heel_requirement(
            vessel_capacity_m3=155_000,
            vessel_class="TFDE",
            actual_heel_m3=155_000 * 0.02,  # only 2%, need 4%
        )
        assert not result.is_sufficient
        assert result.deficit_m3 > 0
        assert result.next_loading_penalty

    def test_heel_ballast_erosion(self):
        """
        A vessel with 6,200 m³ heel (TFDE, 155,000 m³ ship) sailing 15 days
        ballast to Qatar in summer (35°C) should lose some heel to BOG.
        The remaining heel should still be above the minimum.
        """
        initial_heel_m3 = 6_200
        remaining = heel_boiloff_during_ballast(
            heel_volume_m3=initial_heel_m3,
            ballast_days=15.0,
            vessel_class="TFDE",
            ambient_temp_celsius=35.0,
        )
        assert remaining < initial_heel_m3
        assert remaining > 0
        # Should not lose more than ~5% of initial heel over 15 days
        assert remaining > initial_heel_m3 * 0.90


# ---------------------------------------------------------------------------
# ETA tests
# ---------------------------------------------------------------------------

class TestETA:

    def test_ras_laffan_to_futtsu(self):
        """
        Ras Laffan (Qatar) → Futtsu LNG terminal (Tokyo Bay): ~7,000 nm
        Q-Flex at 17 knots → ~17 days sailing time
        Via Malacca Strait (no canal toll).
        """
        result = calculate_eta(
            departure_date_iso="2025-03-01T06:00",
            distance_nm=7_000,
            speed_knots=17.0,
            weather_delay_hours=12.0,  # typical India Ocean squall allowance
        )
        # ~17.3 days sailing + 0.5 day weather
        assert 16.5 < result.transit_days < 18.5
        assert result.eta_iso.startswith("2025-03-")
        assert result.weather_delay_hours == 12.0

    def test_suez_canal_adds_delay(self):
        """
        Sabine Pass (USA) → Zeebrugge (Belgium) via Suez Canal: ~6,400 nm
        Suez transit adds ~16h (8h queuing + 8h transit).
        This changes the slot booking at Zeebrugge.
        """
        without_suez = calculate_eta(
            departure_date_iso="2025-04-01T00:00",
            distance_nm=6_400,
            speed_knots=16.0,
        )
        with_suez = calculate_eta(
            departure_date_iso="2025-04-01T00:00",
            distance_nm=6_400,
            speed_knots=16.0,
            canal_delay_hours=16.0,
        )
        delta_hours = with_suez.total_hours - without_suez.total_hours
        assert abs(delta_hours - 16.0) < 0.01

    def test_invalid_speed_raises(self):
        with pytest.raises(ValueError, match="Speed must be positive"):
            calculate_eta("2025-01-01T00:00", 1000.0, 0.0)


# ---------------------------------------------------------------------------
# Laycan compliance tests
# ---------------------------------------------------------------------------

class TestLaycan:

    def test_on_time_arrival(self):
        result = check_laycan_compliance(
            eta_iso="2025-03-18T14:00",
            laycan_start_iso="2025-03-18T00:00",
            laycan_end_iso="2025-03-19T00:00",
            cargo_volume_mmbtu=3_200_000,
            vessel_class="Q-Flex",
        )
        assert result.status == "ON_TIME"
        assert result.waiting_hours == 0.0
        assert result.delay_hours == 0.0
        assert not result.demurrage_risk

    def test_early_arrival_generates_anchor_bog(self):
        """
        Vessel arrives 18h before laycan opens.
        Must wait at anchor → burning BOG unnecessarily.
        Common when weather is better than forecast.
        """
        result = check_laycan_compliance(
            eta_iso="2025-03-17T06:00",   # 18h early
            laycan_start_iso="2025-03-18T00:00",
            laycan_end_iso="2025-03-19T00:00",
            cargo_volume_mmbtu=3_200_000,
            vessel_class="Q-Flex",
        )
        assert result.status == "EARLY"
        assert abs(result.waiting_hours - 18.0) < 0.1
        assert result.waiting_bog_loss_mmbtu > 0
        assert not result.demurrage_risk  # early is not late

    def test_late_arrival_triggers_demurrage_risk(self):
        """
        Vessel arrives 6h after laycan end.
        Demurrage clock starts from laycan end (not from NOR tendering).
        Scheduler must immediately alert commercial team.
        """
        result = check_laycan_compliance(
            eta_iso="2025-03-19T06:00",   # 6h late
            laycan_start_iso="2025-03-18T00:00",
            laycan_end_iso="2025-03-19T00:00",
            cargo_volume_mmbtu=3_200_000,
            vessel_class="Q-Flex",
        )
        assert result.status == "LATE"
        assert abs(result.delay_hours - 6.0) < 0.1
        assert result.demurrage_risk


# ---------------------------------------------------------------------------
# Demurrage tests
# ---------------------------------------------------------------------------

class TestDemurrage:

    def test_no_demurrage_within_laytime(self):
        result = calculate_demurrage(
            allowed_laytime_hours=24.0,
            actual_port_hours=22.0,
            demurrage_rate_usd_per_day=120_000,
        )
        assert not result.on_demurrage
        assert result.demurrage_usd == 0.0

    def test_demurrage_cost_qflex_typical(self):
        """
        Q-Flex on demurrage for 1.5 days at $120,000/day = $180,000.
        This is a real order of magnitude — schedulers track this in real time.
        """
        result = calculate_demurrage(
            allowed_laytime_hours=24.0,
            actual_port_hours=60.0,    # 36h over laytime
            demurrage_rate_usd_per_day=120_000,
        )
        assert result.on_demurrage
        assert abs(result.demurrage_days - 1.5) < 0.01
        assert abs(result.demurrage_usd - 180_000) < 1.0


# ---------------------------------------------------------------------------
# Cargo volume reconciliation tests
# ---------------------------------------------------------------------------

class TestCargoReconciliation:

    def test_full_voyage_reconciliation(self):
        """
        Full voyage reconciliation for a Q-Flex:
        - Loaded: 3,200,000 mmBtu
        - Heel retained: ~6,300 mmBtu (300 m³ × 21)
        - Transit BOG: ~85,000 mmBtu (17 days, moderate conditions)
        - Waiting BOG: ~1,500 mmBtu (3h anchor wait)
        - Contract: 3,100,000 mmBtu
        → Net deliverable should comfortably exceed contract
        """
        from core.scheduling.physics import BoilOffResult

        # Build a mock BoilOffResult
        transit_bog = calculate_boiloff(
            cargo_volume_mmbtu=3_200_000,
            transit_days=17.0,
            vessel_class="Q-Flex",
            ambient_temp_celsius=28.0,
        )

        result = reconcile_cargo_volume(
            gross_loaded_mmbtu=3_200_000,
            heel_mmbtu=6_300,
            transit_bog=transit_bog,
            waiting_bog_mmbtu=1_500,
            contractual_quantity_mmbtu=3_100_000,
        )

        assert result.net_deliverable_mmbtu > 0
        assert result.quantity_shortfall_mmbtu == 0.0, (
            "Should have surplus, not shortfall on this voyage"
        )
        # Net = 3,200,000 - 6,300 - transit_bog - 1,500
        expected_net_approx = 3_200_000 - 6_300 - transit_bog.gross_bog_mmbtu - 1_500
        assert abs(result.net_deliverable_mmbtu - expected_net_approx) < 1.0


# ---------------------------------------------------------------------------
# Draft compatibility tests
# ---------------------------------------------------------------------------

class TestDraftCompatibility:

    def test_qmax_cannot_berth_at_standard_terminal(self):
        """
        Q-Max draft = 12.5m. Most LNG terminals worldwide are certified to 12.0m.
        Q-Max vessels are typically restricted to Ras Laffan (Qatar) and
        a handful of purpose-built terminals. This is a hard scheduling constraint.
        """
        result = check_draft_compatibility("Q-Max", terminal_max_draft_m=12.0)
        assert not result["compatible"]
        assert result["shortfall_m"] == 0.5
        assert result["alert"] is not None

    def test_tfde_compatible_with_standard_terminal(self):
        result = check_draft_compatibility("TFDE", terminal_max_draft_m=12.0)
        assert result["compatible"]
        assert result["shortfall_m"] == 0.0
        assert result["alert"] is None

    def test_qmax_can_berth_at_ras_laffan(self):
        """Ras Laffan is purpose-built for Q-Max at 14m depth."""
        result = check_draft_compatibility("Q-Max", terminal_max_draft_m=14.0)
        assert result["compatible"]
