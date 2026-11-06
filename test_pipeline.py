"""
TripCrew Backend Platform - Phase 2 (Quality)
Comprehensive Verification & Test Suite
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from main import app, ensure_startup_resources
from graph import run_inquiry_pipeline
from models import TripBrief


def test_clarification_flow():
    print("\n" + "=" * 60)
    print("TEST 1: Clarification Flow (Missing Required Information)")
    print("=" * 60)

    # Incomplete inquiry: missing origin, group size, and budget
    incomplete_message = "Looking to plan a Goa trip for 4 nights in late November!"
    result: TripBrief = run_inquiry_pipeline(raw_message=incomplete_message)

    print(f"Status: {result.status}")
    print(f"Missing Fields: {result.missing_fields}")
    print(f"Clarification Question: {result.clarification_question}")

    assert result.status == "needs_clarification", f"Expected needs_clarification, got {result.status}"
    assert "origin" in result.missing_fields, "Origin should be identified as missing"
    assert "group_size" in result.missing_fields, "Group size should be identified as missing"
    assert "budget" in result.missing_fields, "Budget should be identified as missing"
    assert result.clarification_question is not None, "Clarification question should be generated"
    assert result.itinerary == [], "Itinerary should not be generated when clarification is needed"
    assert result.quotes is None, "Quotes should not be generated when clarification is needed"
    assert result.pdf_path is None, "PDF should not be generated when clarification is needed"
    print(">>> TEST 1 PASSED: Conditional routing successfully stopped at intake with clarification question.")


def test_full_pipeline_flow():
    print("\n" + "=" * 60)
    print("TEST 2: Full End-to-End Pipeline with Critic Validator")
    print("=" * 60)

    # Complete inquiry
    complete_message = (
        "Goa trip for 4 friends, 25k budget each, 4 nights in late November departing from Mumbai. "
        "We want beach parties, water sports, and relaxed seafood dinners."
    )
    result: TripBrief = run_inquiry_pipeline(
        raw_message=complete_message,
        client_name="Aditya Verma",
        contact="+91-9876543210",
    )

    print(f"Status: {result.status}")
    print(f"Client: {result.client.name} ({result.client.contact})")
    print(f"Origin: {result.trip_basics.origin}")
    print(f"Destination: {result.trip_basics.destination}")
    print(f"Duration: {result.trip_basics.duration_days} Days / {result.trip_basics.duration_nights} Nights")
    print(f"Group Size: {result.trip_basics.group_size}")
    print(f"Target Budget pp: ₹{result.budget.target_budget_per_person:,.0f}")
    print(f"Preferences: {result.preferences_and_constraints.interests}")

    # Assert extraction
    assert result.status == "completed", f"Expected completed, got {result.status}"
    assert result.trip_basics.destination.lower() == "goa"
    assert result.trip_basics.origin.lower() == "mumbai"
    assert result.trip_basics.group_size == 4
    assert result.trip_basics.duration_nights == 4
    assert result.trip_basics.duration_days == 5
    assert result.budget.target_budget_per_person == 25000.0

    # Assert Weather & Visa Advisories
    assert result.destination_weather is not None, "Live destination weather must be populated"
    print(f"Weather: {result.destination_weather.condition} ({result.destination_weather.temperature_high_c}°C)")
    assert result.visa_advisory is not None, "Visa advisory must be populated"
    print(f"Visa Advisory: {result.visa_advisory}")

    # Assert Validator Critic Output
    val = result.validation_result
    assert val is not None, "ValidationResult must be present from Critic Node"
    print(f"\nCritic Feasibility Score: {val.feasibility_score * 100:.0f}%")
    print(f"Pillars Passed: Opening Hours={val.opening_hours_passed}, Logistics={val.travel_logistics_passed}, Budget={val.budget_passed}, Visa={val.visa_rules_passed}")
    assert val.is_valid is True, "Itinerary must pass validation"
    assert val.feasibility_score >= 0.90, "Feasibility score must be >= 0.90"

    # Assert Itinerary Generation
    print(f"\nGenerated Itinerary Days: {len(result.itinerary)}")
    assert len(result.itinerary) == 5, f"Expected 5 day plans, got {len(result.itinerary)}"
    for day in result.itinerary:
        print(f"  Day {day.day_number}: {day.title} ({len(day.activities)} activities)")
        assert len(day.activities) > 0, f"Day {day.day_number} has no activities"
        assert day.day_rationale, f"Day {day.day_number} missing rationale"

    # Assert Tiered Pricing Math
    print("\nTiered Quotes Breakdown:")
    q = result.quotes
    assert q is not None, "QuotesSummary must be present"
    assert q.budget_tier is not None, "Budget tier must be present"
    assert q.standard_tier is not None, "Standard tier must be present"
    assert q.premium_tier is not None, "Premium tier must be present"

    for tier in [q.budget_tier, q.standard_tier, q.premium_tier]:
        br = tier.breakdown
        print(f"\n  [{tier.tier_name.upper()} TIER]")
        print(f"    Hotel: {br.hotel_name} ({br.rooms_count} rooms @ ₹{br.hotel_cost_per_room_night:,.0f}/nt) = ₹{br.hotel_total_cost:,.0f}")
        print(f"    Transfers: {br.transfer_type} = ₹{br.transfers_total_cost:,.0f}")
        print(f"    Activities: {br.activity_description} = ₹{br.activities_total_cost:,.0f}")
        print(f"    Base Net Cost: ₹{br.subtotal_base_cost:,.0f}")
        print(f"    Agency Margin (15%): ₹{br.agency_margin_amount:,.0f}")
        print(f"    Total Group Quote: ₹{br.grand_total_group_cost:,.0f}")
        print(f"    Final Quote Per Person: ₹{br.total_quote_per_person:,.0f}")
        print(f"    Note: {br.budget_comparison_note}")

        expected_base = br.hotel_total_cost + br.transfers_total_cost + br.activities_total_cost
        assert abs(br.subtotal_base_cost - expected_base) < 1.0, "Base cost math mismatch"
        expected_margin = round(expected_base * 0.15, 2)
        assert abs(br.agency_margin_amount - expected_margin) < 1.0, "Margin math mismatch"
        expected_grand = round(expected_base + expected_margin, 2)
        assert abs(br.grand_total_group_cost - expected_grand) < 1.0, "Grand total math mismatch"
        expected_pp = round(expected_grand / 4, 2)
        assert abs(br.total_quote_per_person - expected_pp) < 1.0, "Per person math mismatch"

    # Assert PDF generation
    assert result.pdf_path is not None, "PDF path must not be None"
    pdf_file = Path(result.pdf_path)
    assert pdf_file.exists(), f"PDF file does not exist at {pdf_file}"
    pdf_size = pdf_file.stat().st_size
    print(f"\nGenerated PDF Quote File: {pdf_file.name}")
    print(f"PDF File Size: {pdf_size:,} bytes")
    assert pdf_size > 1000, "PDF file size too small (likely corrupt or empty)"
    print(">>> TEST 2 PASSED: Full itinerary validated by Critic, 3 tiers dynamically priced, and quality PDF generated!")


def test_re_planning_loop():
    print("\n" + "=" * 60)
    print("TEST 3: Re-Planning Loop (Automated Critic Self-Correction)")
    print("=" * 60)

    # Active pace triggers an initial schedule error that the Critic catches and corrects
    active_inquiry = (
        "Fast-paced action-packed Goa trip for 4 friends from Pune, 4 nights in late November, 25k budget each. "
        "We want packed schedules and active water sports."
    )
    result: TripBrief = run_inquiry_pipeline(raw_message=active_inquiry)

    print(f"Final Status: {result.status}")
    print(f"Total Re-planning Iterations Triggered: {result.replan_count}")
    print(f"Validator Feedback History: {result.validator_feedback_history}")
    print(f"Final Feasibility Score: {result.validation_result.feasibility_score * 100:.0f}%")

    assert result.status == "completed", "Pipeline must complete successfully"
    assert result.replan_count >= 1, "Re-planning loop must be triggered at least once"
    assert result.replan_count <= result.max_retries, "Re-planning must strictly obey max_retries limit"
    assert result.validation_result.is_valid is True, "Final revised itinerary must be valid"
    assert result.validation_result.feasibility_score >= 0.90, "Final feasibility score must be >= 0.90"
    print(">>> TEST 3 PASSED: Critic node successfully detected scheduling error and triggered automated replanning loop!")


def test_fastapi_endpoints():
    print("\n" + "=" * 60)
    print("TEST 4: FastAPI REST API Endpoints with Quality Gates")
    print("=" * 60)

    ensure_startup_resources()
    client = TestClient(app)

    # 1. Health check with live integrations
    res_health = client.get("/health")
    assert res_health.status_code == 200
    health_data = res_health.json()
    print(f"GET /health: {health_data}")
    assert health_data["status"] == "healthy"
    assert "integrations" in health_data

    # 2. Inquiry endpoint with clarification required
    res_clarify = client.post(
        "/api/v1/inquiry",
        json={"message": "I want to visit Jaipur sometime next month"},
    )
    assert res_clarify.status_code == 200
    data_clarify = res_clarify.json()
    print(f"POST /api/v1/inquiry (Clarification): status={data_clarify['status']}")
    print(f"  Question: {data_clarify['question']}")
    assert data_clarify["status"] == "needs_clarification"
    assert "missing_fields" in data_clarify
    assert len(data_clarify["missing_fields"]) > 0

    # 3. Inquiry endpoint with complete trip details
    res_complete = client.post(
        "/api/v1/inquiry",
        json={
            "message": "Goa trip for 4 friends, 25k budget each, 4 nights in late November departing from Mumbai",
            "client_name": "Rohan Sharma",
            "contact": "rohan@example.com",
        },
    )
    assert res_complete.status_code == 200
    data_complete = res_complete.json()
    print(f"POST /api/v1/inquiry (Complete): status={data_complete['status']}")
    print(f"  Validation Summary: {data_complete.get('validation_summary')}")
    print(f"  PDF URL: {data_complete['pdf_download_url']}")
    print(f"  Local Path: {data_complete['pdf_file_path']}")
    assert data_complete["status"] == "completed"
    assert data_complete["validation_summary"] is not None
    assert data_complete["validation_summary"]["is_valid"] is True
    assert data_complete["pdf_download_url"] is not None
    assert data_complete["pdf_file_path"] is not None

    # 4. Download PDF endpoint
    pdf_filename = Path(data_complete["pdf_file_path"]).name
    res_pdf = client.get(f"/api/v1/quotes/{pdf_filename}")
    assert res_pdf.status_code == 200
    assert res_pdf.headers["content-type"] == "application/pdf"
    print(f"GET /api/v1/quotes/{pdf_filename}: Received {len(res_pdf.content):,} bytes of PDF data")

    print(">>> TEST 4 PASSED: All FastAPI endpoints with Quality validation behaving correctly!")


if __name__ == "__main__":
    test_clarification_flow()
    test_full_pipeline_flow()
    test_re_planning_loop()
    test_fastapi_endpoints()
    print("\n" + "=" * 60)
    print("ALL TRIPCREW BACKEND PHASE 2 (QUALITY) TESTS PASSED!")
    print("=" * 60)
