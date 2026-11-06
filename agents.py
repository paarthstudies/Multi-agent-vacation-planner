"""
TripCrew Backend Platform - Phase 1 MVP
Agent Nodes Implementation (Intake, Itinerary, Budget, Document)
"""

import os
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from pydantic import BaseModel, Field

from models import (
    TripBrief,
    ClientInfo,
    TripBasics,
    BudgetConstraint,
    PreferencesAndConstraints,
    DayPlan,
    ActivityItem,
    TierQuote,
    TierCostBreakdown,
    QuotesSummary,
)

# Optional Anthropic integration
try:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.messages import SystemMessage, HumanMessage
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


# Extraction schema used with Claude structured output
class IntakeExtraction(BaseModel):
    client_name: Optional[str] = Field(None, description="Customer name if mentioned")
    origin: Optional[str] = Field(None, description="Departure city or airport")
    destination: Optional[str] = Field(None, description="Trip destination city or region")
    travel_dates: Optional[str] = Field(None, description="Travel dates or timeframe (e.g. late November)")
    duration_days: Optional[int] = Field(None, description="Total days for the trip")
    duration_nights: Optional[int] = Field(None, description="Total nights for the trip")
    group_size: Optional[int] = Field(None, description="Total number of travelers")
    budget_per_person: Optional[float] = Field(None, description="Budget per person in local currency (e.g. 25000)")
    total_budget: Optional[float] = Field(None, description="Total group budget")
    currency: str = Field("INR", description="Currency code")
    pace: Optional[str] = Field("Moderate", description="Trip pace: Relaxed, Moderate, or Fast-paced")
    dietary_requirements: List[str] = Field(default_factory=list, description="Dietary preferences")
    must_haves: List[str] = Field(default_factory=list, description="Explicit must-haves or activities")
    interests: List[str] = Field(default_factory=list, description="General interests like nightlife, beach, heritage")


class GeneratedItinerarySchema(BaseModel):
    days: List[DayPlan] = Field(..., description="List of day-by-day plans")


def get_llm():
    """Initializes ChatAnthropic if API key is present."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if ANTHROPIC_AVAILABLE and api_key and api_key.startswith("sk-ant"):
        return ChatAnthropic(
            model_name="claude-3-5-sonnet-20241022",
            temperature=0.2,
            anthropic_api_key=api_key,
        )
    return None


# ============================================================================
# AGENT 1: INTAKE AGENT
# ============================================================================

def _heuristic_intake_parse(text: str) -> IntakeExtraction:
    """
    Robust rule-based and regex extraction fallback when Claude API is not configured.
    Handles phrases like:
    'Goa trip for 4 friends, 25k budget each, 4 nights in late November departing from Mumbai'
    """
    lower = text.lower()

    # 1. Destination detection
    dest_candidates = ["goa", "jaipur", "kerala", "manali", "udaipur", "munnar", "shimla", "rishikesh", "agra", "varanasi", "andaman"]
    destination = None
    for cand in dest_candidates:
        if cand in lower:
            destination = cand.capitalize()
            break

    # 2. Origin detection
    origin = None
    origin_match = re.search(r"(?:from|departing from|leaving from|flying from|out of)\s+([a-zA-Z]+)", text, re.IGNORECASE)
    if origin_match:
        origin = origin_match.group(1).capitalize()
    else:
        # Common departure hubs if mentioned standalone
        for hub in ["mumbai", "delhi", "bangalore", "bengaluru", "hyderabad", "chennai", "kolkata", "pune", "ahmedabad"]:
            if re.search(rf"\b{hub}\b", lower) and hub != (destination or "").lower():
                origin = hub.capitalize()
                break

    # 3. Group size detection
    group_size = None
    group_match = re.search(r"(\d+)\s*(?:people|friends|adults|persons|pax|travelers|members|guests)", lower)
    if group_match:
        group_size = int(group_match.group(1))
    elif "couple" in lower or "husband and wife" in lower or "me and my partner" in lower or "2 of us" in lower:
        group_size = 2
    elif "solo" in lower or "just me" in lower or "myself" in lower:
        group_size = 1
    elif "family of 4" in lower:
        group_size = 4
    elif "family of 3" in lower:
        group_size = 3

    # 4. Duration detection
    duration_nights = None
    duration_days = None
    night_match = re.search(r"(\d+)\s*(?:nights|night|n)\b", lower)
    day_match = re.search(r"(\d+)\s*(?:days|day|d)\b", lower)

    if night_match:
        duration_nights = int(night_match.group(1))
        duration_days = duration_nights + 1
    elif day_match:
        duration_days = int(day_match.group(1))
        duration_nights = max(1, duration_days - 1)

    # 5. Travel dates / timeframe
    travel_dates = None
    date_patterns = [
        r"(?:in\s+)?(late\s+[a-zA-Z]+|early\s+[a-zA-Z]+|mid\s+[a-zA-Z]+)",
        r"(?:in\s+)?([a-zA-Z]+\s+\d{4})",
        r"(?:on\s+)?(\d{1,2}(?:st|nd|rd|th)?\s+[a-zA-Z]+(?:\s+\d{4})?)",
        r"(?:next\s+weekend|this\s+weekend|diwali|christmas|new\s+year)",
        r"(?:in\s+)?(january|february|march|april|may|june|july|august|september|october|november|december)",
    ]
    for pat in date_patterns:
        m = re.search(pat, lower)
        if m:
            travel_dates = m.group(0).strip()
            break

    # 6. Budget detection
    budget_per_person = None
    total_budget = None

    # Matches "25k budget each", "25,000 per person", "30k each", "25000 pp"
    pp_budget_match = re.search(
        r"(?:rs\.?|inr|₹)?\s*(\d+(?:\.\d+)?)\s*(k|thousand)?\s*(?:budget\s+each|budget\s+per\s+person|per\s+person|each|pp|a\s+head)\b",
        lower,
    )
    if pp_budget_match:
        val = float(pp_budget_match.group(1))
        mult = 1000 if pp_budget_match.group(2) else 1
        budget_per_person = val * mult
    else:
        # Check generic number with "k" or thousands
        k_match = re.search(r"(\d+)\s*k\b", lower)
        num_match = re.search(r"(?:budget\s*(?:of|is)?\s*(?:rs\.?|inr|₹)?\s*)(\d{4,7})", lower)
        if k_match:
            budget_per_person = float(k_match.group(1)) * 1000
        elif num_match:
            budget_per_person = float(num_match.group(1))

    # 7. Preferences, Pace, Dietary
    pace = "Moderate"
    if "relaxed" in lower or "chill" in lower or "leisure" in lower:
        pace = "Relaxed"
    elif "packed" in lower or "active" in lower or "fast" in lower or "action-packed" in lower:
        pace = "Active"

    dietary = []
    if "veg" in lower or "vegetarian" in lower:
        dietary.append("Vegetarian")
    if "jain" in lower:
        dietary.append("Jain")
    if "halal" in lower:
        dietary.append("Halal")
    if "seafood" in lower:
        dietary.append("Seafood-friendly")

    interests = []
    for trait in ["nightlife", "beaches", "heritage", "water sports", "scenic", "nature", "shopping", "food", "cafes", "parties"]:
        if trait in lower:
            interests.append(trait.title())

    must_haves = []
    if "private pool" in lower or "villa" in lower:
        must_haves.append("Private Pool Villa")
    if "sunset cruise" in lower:
        must_haves.append("Sunset Cruise")
    if "scuba" in lower:
        must_haves.append("Scuba Diving")
    if "heritage walk" in lower:
        must_haves.append("Heritage Walk")

    return IntakeExtraction(
        origin=origin,
        destination=destination,
        travel_dates=travel_dates,
        duration_days=duration_days,
        duration_nights=duration_nights,
        group_size=group_size,
        budget_per_person=budget_per_person,
        total_budget=total_budget,
        currency="INR",
        pace=pace,
        dietary_requirements=dietary,
        must_haves=must_haves,
        interests=interests,
    )


def intake_agent(state: TripBrief) -> Dict[str, Any]:
    """
    Intake Agent Node:
    1. Parses raw customer text into structured fields.
    2. Validates mandatory fields: origin, destination, dates/duration, group_size, budget.
    3. If critical info is missing, flags status='needs_clarification' and generates a clarifying question.
    """
    raw_text = state.raw_inquiry
    llm = get_llm()

    extracted: Optional[IntakeExtraction] = None

    if llm:
        try:
            structured_llm = llm.with_structured_output(IntakeExtraction)
            prompt = (
                "You are the TripCrew Intake AI specialist. Extract the travel requirements from this user inquiry. "
                "Normalize numbers, currencies, durations, and preferences accurately into the structured schema.\n\n"
                f"Customer Inquiry: \"{raw_text}\""
            )
            extracted = structured_llm.invoke(prompt)
        except Exception as e:
            # Fall back to heuristic parser gracefully
            extracted = _heuristic_intake_parse(raw_text)
    else:
        extracted = _heuristic_intake_parse(raw_text)

    # Populate TripBasics & Budget from extraction (preserving any existing state)
    updated_client = state.client.model_copy()
    if extracted.client_name:
        updated_client.name = extracted.client_name

    updated_basics = state.trip_basics.model_copy(
        update={
            "origin": extracted.origin or state.trip_basics.origin,
            "destination": extracted.destination or state.trip_basics.destination,
            "travel_dates": extracted.travel_dates or state.trip_basics.travel_dates,
            "duration_days": extracted.duration_days or state.trip_basics.duration_days,
            "duration_nights": extracted.duration_nights or state.trip_basics.duration_nights,
            "group_size": extracted.group_size or state.trip_basics.group_size,
        }
    )

    # Normalize duration if one of days/nights is available
    if updated_basics.duration_nights and not updated_basics.duration_days:
        updated_basics.duration_days = updated_basics.duration_nights + 1
    elif updated_basics.duration_days and not updated_basics.duration_nights:
        updated_basics.duration_nights = max(1, updated_basics.duration_days - 1)

    updated_budget = state.budget.model_copy(
        update={
            "target_budget_per_person": extracted.budget_per_person or state.budget.target_budget_per_person,
            "total_target_budget": extracted.total_budget or state.budget.total_target_budget,
            "currency": extracted.currency or state.budget.currency,
        }
    )

    # If total budget given but not per person
    if updated_budget.total_target_budget and updated_basics.group_size and not updated_budget.target_budget_per_person:
        updated_budget.target_budget_per_person = round(
            updated_budget.total_target_budget / updated_basics.group_size, 2
        )
    elif updated_budget.target_budget_per_person and updated_basics.group_size and not updated_budget.total_target_budget:
        updated_budget.total_target_budget = round(
            updated_budget.target_budget_per_person * updated_basics.group_size, 2
        )

    updated_prefs = state.preferences_and_constraints.model_copy(
        update={
            "pace": extracted.pace or state.preferences_and_constraints.pace or "Moderate",
            "dietary_requirements": list(set(state.preferences_and_constraints.dietary_requirements + extracted.dietary_requirements)),
            "must_haves": list(set(state.preferences_and_constraints.must_haves + extracted.must_haves)),
            "interests": list(set(state.preferences_and_constraints.interests + extracted.interests)),
        }
    )

    # Validation of required fields
    missing_fields = []
    if not updated_basics.origin:
        missing_fields.append("origin")
    if not updated_basics.destination:
        missing_fields.append("destination")
    if not (updated_basics.duration_days or updated_basics.duration_nights or updated_basics.travel_dates):
        missing_fields.append("travel_dates_or_duration")
    if not updated_basics.group_size or updated_basics.group_size <= 0:
        missing_fields.append("group_size")
    if not (updated_budget.target_budget_per_person or updated_budget.total_target_budget):
        missing_fields.append("budget")

    if missing_fields:
        # Formulate clarifying question
        clarification_prompts = []
        if "origin" in missing_fields:
            clarification_prompts.append("where will your group be departing from?")
        if "destination" in missing_fields:
            clarification_prompts.append("which destination are you planning to visit?")
        if "travel_dates_or_duration" in missing_fields:
            clarification_prompts.append("what dates or number of nights/days do you have in mind?")
        if "group_size" in missing_fields:
            clarification_prompts.append("how many travelers will be in your group?")
        if "budget" in missing_fields:
            clarification_prompts.append("what approximate budget per person (or total) are you aiming for?")

        dest_mention = f" {updated_basics.destination}" if updated_basics.destination else ""
        friendly_question = (
            f"We're excited to design your dream{dest_mention} vacation! To craft an exact itinerary and tier-priced quote, "
            f"could you please clarify: {'; '.join(clarification_prompts).capitalize()}"
        )

        return {
            "client": updated_client,
            "trip_basics": updated_basics,
            "budget": updated_budget,
            "preferences_and_constraints": updated_prefs,
            "status": "needs_clarification",
            "missing_fields": missing_fields,
            "clarification_question": friendly_question,
        }

    return {
        "client": updated_client,
        "trip_basics": updated_basics,
        "budget": updated_budget,
        "preferences_and_constraints": updated_prefs,
        "status": "in_progress",
        "missing_fields": [],
        "clarification_question": None,
    }


# ============================================================================
# AGENT 2: ITINERARY AGENT
# ============================================================================

def _generate_destination_itinerary(
    destination: str,
    days: int,
    group_size: int,
    pace: str,
    interests: List[str],
    origin: str,
) -> List[DayPlan]:
    """
    High-fidelity itinerary generator creating authentic, geo-specific day schedules
    with realistic pacing, locations, and travel gaps for domestic destinations.
    """
    dest_lower = (destination or "Goa").lower()
    day_plans: List[DayPlan] = []

    if "goa" in dest_lower:
        # Authentic Goa template
        templates = [
            (
                "Arrival & Coastal Sundowner at Anjuna",
                "Arrive in sunny Goa, settle into your accommodation, and unwind with beachfront sunset drinks.",
                [
                    ActivityItem(
                        time_slot="12:00 PM - 02:30 PM",
                        title="Arrival, Airport Transfer & Resort Check-in",
                        description=f"Airport reception from {origin} flight, private transfer across the Mandovi estuary, and welcome drinks at resort.",
                        location="North Goa / Coastal Belt",
                        estimated_travel_gap="55 min scenic transfer from Dabolim/MOPA",
                    ),
                    ActivityItem(
                        time_slot="03:30 PM - 05:30 PM",
                        title="Unwind at Anjuna Beach & Shack Culture",
                        description="Casual seaside stroll along red cliffside sands, fresh coconut water, and local seafood bites.",
                        location="Anjuna Beach",
                        estimated_travel_gap="15 min local transfer",
                    ),
                    ActivityItem(
                        time_slot="06:00 PM - 09:30 PM",
                        title="Sundowner Drinks & Curated Welcome Dinner",
                        description="Watch the Arabian Sea sunset from a famous clifftop lounge (Curlies/Purple Martini) followed by Goan coastal curry dinner.",
                        location="Vagator / Anjuna Cliff",
                        estimated_travel_gap="10 min drive",
                    ),
                ],
                f"Designed with a {pace.lower()} arrival pace allowing the group of {group_size} to shake off travel fatigue without missing Goa's signature sunset.",
            ),
            (
                "Fort Heritage, Beachfront Water Sports & Calangute Buzz",
                "A balanced mix of 17th-century Portuguese coastal history and thrilling aquatic sports.",
                [
                    ActivityItem(
                        time_slot="09:00 AM - 11:30 AM",
                        title="Aguada Fort & Historic Lighthouse Exploration",
                        description="Panoramic views over Sinquerim bay, exploration of Portuguese ramparts and freshwater spring bastion.",
                        location="Sinquerim / Candolim",
                        estimated_travel_gap="25 min drive along scenic coastline",
                    ),
                    ActivityItem(
                        time_slot="12:30 PM - 03:00 PM",
                        title="Water Sports Action & Beachside Lunch",
                        description="Jet-skiing, bumper rides, and parasailing over Arabian waves, followed by chilled lunch at a beachfront shack.",
                        location="Calangute / Baga Coast",
                        estimated_travel_gap="15 min drive",
                    ),
                    ActivityItem(
                        time_slot="04:30 PM - 07:00 PM",
                        title="Mandovi River Twilight Catamaran Cruise",
                        description="Live Goan folk music, sunset viewing on the calm river waters, and breezy cocktail reception.",
                        location="Panjim Jetty",
                        estimated_travel_gap="30 min transfer",
                    ),
                ],
                "Groups activities geographically in North Goa to minimize transit times while maximizing daylight thrills.",
            ),
            (
                "Old Goa UNESCO Churches & Latin Quarter Heritage Stroll",
                "Immerse in Portuguese architecture, colorful heritage alleys, and authentic Indo-Portuguese dining.",
                [
                    ActivityItem(
                        time_slot="09:30 AM - 12:00 PM",
                        title="Basilica of Bom Jesus & Se Cathedral",
                        description="Walk through centuries-old Baroque cathedrals, golden altars, and UNESCO World Heritage sanctuaries.",
                        location="Old Goa (Velha Goa)",
                        estimated_travel_gap="35 min transfer",
                    ),
                    ActivityItem(
                        time_slot="12:30 PM - 03:30 PM",
                        title="Fontainhas Heritage Walk & Indo-Portuguese Lunch",
                        description="Wander vibrant yellow and cobalt-blue lanes of Fontainhas, visiting heritage bakeries and sampling traditional Chicken Cafreal & Bebinca.",
                        location="Fontainhas, Panaji",
                        estimated_travel_gap="20 min drive",
                    ),
                    ActivityItem(
                        time_slot="05:30 PM - 08:30 PM",
                        title="Spice Plantation Tour & Evening Cafe Crawl",
                        description="Guided botanical walk through aromatic cardamom, cinnamon, and vanilla groves with traditional banana-leaf buffet.",
                        location="Ponda Foothills",
                        estimated_travel_gap="40 min drive",
                    ),
                ],
                "Provides cultural depth and culinary discovery to balance the beach experiences, matching client interest in authentic local flair.",
            ),
            (
                "South Goa Pristine Sands & Sunset Sailing",
                "Experience the tranquil, uncrowded white sand beaches of South Goa and a curated sunset cruise.",
                [
                    ActivityItem(
                        time_slot="10:00 AM - 01:00 PM",
                        title="Palolem & Butterfly Beach Kayaking",
                        description="Gentle turquoise waters, sea kayaking around rocky headlands, and dolphin spotting near Butterfly Beach.",
                        location="Palolem, South Goa",
                        estimated_travel_gap="60 min scenic highway drive",
                    ),
                    ActivityItem(
                        time_slot="01:30 PM - 04:00 PM",
                        title="Artisan Seafood Lunch at Agonda",
                        description="Fresh catch of the day (kingfish, butter garlic crab) under palm thatch overlooking tranquil Agonda surf.",
                        location="Agonda Beach",
                        estimated_travel_gap="15 min drive",
                    ),
                    ActivityItem(
                        time_slot="05:30 PM - 09:30 PM",
                        title="Sunset Bonfire & Farewell Beach Barbecue",
                        description="Private beachside barbecue setup under starry skies with acoustic melodies and tropical mocktails.",
                        location="Cavelossim / Benaulim Beach",
                        estimated_travel_gap="25 min drive",
                    ),
                ],
                "Dedicated day to South Goa's laid-back luxury, giving travelers peaceful coastal serenity before departure.",
            ),
            (
                "Morning Souvenir Walk, Beachside Brunch & Departure",
                "Wrap up the trip with relaxed shopping for cashews, feni, and spices followed by farewell airport transfer.",
                [
                    ActivityItem(
                        time_slot="09:30 AM - 11:30 AM",
                        title="Artisan Market & Goan Delicacies Shopping",
                        description="Pick up roasted spiced cashews, Goan chorizo sausages, handmade ceramic souvenirs, and Bebinca treats.",
                        location="Mapusa / Panjim Municipal Market",
                        estimated_travel_gap="20 min drive",
                    ),
                    ActivityItem(
                        time_slot="12:00 PM - 02:00 PM",
                        title="Farewell Seaside Brunch & Check-out",
                        description="Leisurely multi-course brunch overlooking the waves, final group photos, and checkout procedures.",
                        location="Resort Lounge",
                        estimated_travel_gap="10 min resort stroll",
                    ),
                    ActivityItem(
                        time_slot="02:30 PM - 04:30 PM",
                        title="Private Airport Transfer & Departure",
                        description=f"Chauffeured vehicle transfer to airport for onward journey back to {origin}.",
                        location="Dabolim / MOPA Airport",
                        estimated_travel_gap="50 min transfer with buffer",
                    ),
                ],
                "Generous travel buffers ensure a relaxed, stress-free departure for all group members.",
            ),
        ]
    else:
        # Generic domestic holiday template (Jaipur, Kerala, Manali, etc.)
        templates = [
            (
                f"Arrival & Destination Welcome in {destination}",
                f"Welcome to {destination}. Check-in, relax, and savor an introductory evening exploration.",
                [
                    ActivityItem(
                        time_slot="12:00 PM - 02:30 PM",
                        title="Arrival Reception & Hotel Check-in",
                        description=f"Airport/station pickup from {origin} arrival and transfer to hotel.",
                        location=f"{destination} City Center",
                        estimated_travel_gap="45 min drive",
                    ),
                    ActivityItem(
                        time_slot="04:00 PM - 07:00 PM",
                        title="Local Landmarks & Orientation Walk",
                        description="Gentle guided walk through iconic streets, artisan markets, and tea tastings.",
                        location="Heritage Promenade",
                        estimated_travel_gap="15 min drive",
                    ),
                    ActivityItem(
                        time_slot="07:30 PM - 09:30 PM",
                        title="Authentic Regional Welcome Dinner",
                        description="Multi-course regional thali dinner showcasing traditional spices and recipes.",
                        location="Signature Restaurant",
                        estimated_travel_gap="10 min stroll",
                    ),
                ],
                f"Gentle {pace.lower()} pace ensuring {group_size} travelers adjust to the destination climate.",
            ),
            (
                f"Iconic Landmarks & Cultural Highlights of {destination}",
                f"Full day discovering the most celebrated sights, architecture, and viewpoints in {destination}.",
                [
                    ActivityItem(
                        time_slot="09:00 AM - 12:30 PM",
                        title="Historic Palaces / Monasteries / Nature Reserves",
                        description="Guided in-depth tour of premier architectural marvels with photo stops.",
                        location="North Valley / Royal Quarter",
                        estimated_travel_gap="30 min transfer",
                    ),
                    ActivityItem(
                        time_slot="01:00 PM - 03:00 PM",
                        title="Traditional Gastronomy Experience",
                        description="Curated lunch featuring organic regional dishes and refreshing beverages.",
                        location="Heritage Courtyard Dining",
                        estimated_travel_gap="15 min drive",
                    ),
                    ActivityItem(
                        time_slot="04:00 PM - 06:30 PM",
                        title="Scenic Sunset Viewpoint Excursion",
                        description="Drive up to the highest viewpoint for sunset photography over the horizon.",
                        location="Sunset Hill Point",
                        estimated_travel_gap="25 min drive",
                    ),
                ],
                "Combines cultural sightseeing with scenic golden hour viewpoints.",
            ),
            (
                f"Outdoor Adventures & Artisan Bazaar Trails",
                "Hands-on experiences, light outdoor thrills, and vibrant shopping for local handicrafts.",
                [
                    ActivityItem(
                        time_slot="09:30 AM - 01:00 PM",
                        title="Nature Excursion / Guided Trail Adventure",
                        description="Trek, boat safari, or valley excursion tailored to group energy.",
                        location="Nature Sanctuary / Countryside",
                        estimated_travel_gap="40 min drive",
                    ),
                    ActivityItem(
                        time_slot="01:30 PM - 03:30 PM",
                        title="Riverside / Mountain Cafe Lunch",
                        description="Relaxed lunch at a picturesque artisan cafe.",
                        location="Artisan District",
                        estimated_travel_gap="20 min drive",
                    ),
                    ActivityItem(
                        time_slot="04:30 PM - 07:30 PM",
                        title="Crafts Bazaar & Master Artisan Workshops",
                        description="Observe traditional textiles, pottery, or carvings, and shop directly from artisans.",
                        location="Old Bazaar",
                        estimated_travel_gap="15 min drive",
                    ),
                ],
                "Balances active daytime exploration with leisurely shopping and dining.",
            ),
            (
                f"Hidden Gems & Local Village Exploration",
                "Step off the beaten path to explore tranquil hamlets and local folklore.",
                [
                    ActivityItem(
                        time_slot="10:00 AM - 01:00 PM",
                        title="Village Immersion & Organic Farm Visit",
                        description="Interact with local community, visit organic plantations, and taste fresh produce.",
                        location="Outskirts Rural Valley",
                        estimated_travel_gap="35 min drive",
                    ),
                    ActivityItem(
                        time_slot="01:30 PM - 04:00 PM",
                        title="Community Homestyle Lunch",
                        description="Slow-cooked traditional meal prepared with garden herbs and clay pots.",
                        location="Village Estate",
                        estimated_travel_gap="10 min walk",
                    ),
                    ActivityItem(
                        time_slot="06:00 PM - 09:00 PM",
                        title="Cultural Performance & Bonfire Evening",
                        description="Traditional music and folk dance performance under the stars.",
                        location="Open-air Amphitheater",
                        estimated_travel_gap="25 min drive",
                    ),
                ],
                "Curated for deep regional immersion and memorable evening entertainment.",
            ),
            (
                "Farewell Mornings & Departure",
                f"Last-minute souvenir hunting, farewell breakfast, and seamless return transfer to {origin}.",
                [
                    ActivityItem(
                        time_slot="09:00 AM - 11:30 AM",
                        title="Leisurely Breakfast & Souvenir Collection",
                        description="Final stroll through local spice and craft markets, savoring last tastes.",
                        location="City Arcade",
                        estimated_travel_gap="15 min drive",
                    ),
                    ActivityItem(
                        time_slot="12:00 PM - 02:30 PM",
                        title="Hotel Check-out & Airport / Station Drop-off",
                        description=f"Chauffeured vehicle transfer for departure back to {origin}.",
                        location="Terminal Gate",
                        estimated_travel_gap="45 min transfer",
                    ),
                ],
                "Ensures punctual check-out and peaceful departure without rushing.",
            ),
        ]

    # Select the required number of days
    total_days = max(1, days)
    for d in range(total_days):
        template_idx = min(d, len(templates) - 1)
        # If trip is longer than template list, reuse middle days
        if d == total_days - 1 and total_days > 1:
            template_idx = len(templates) - 1
        elif d >= len(templates) - 1:
            template_idx = 1

        title, summary, activities, rationale = templates[template_idx]
        day_plans.append(
            DayPlan(
                day_number=d + 1,
                title=f"Day {d + 1}: {title}",
                summary=summary,
                activities=activities,
                day_rationale=rationale,
            )
        )

    return day_plans


def itinerary_agent(state: TripBrief) -> Dict[str, Any]:
    """
    Itinerary Agent Node:
    Constructs an authentic, sequenced day-by-day plan using Claude (if available)
    or the high-fidelity destination engine.
    """
    destination = state.trip_basics.destination or "Goa"
    origin = state.trip_basics.origin or "Origin City"
    days = state.trip_basics.duration_days or 5
    group_size = state.trip_basics.group_size or 4
    pace = state.preferences_and_constraints.pace or "Moderate"
    interests = state.preferences_and_constraints.interests or []
    must_haves = state.preferences_and_constraints.must_haves or []

    llm = get_llm()
    itinerary_days: Optional[List[DayPlan]] = None

    if llm:
        try:
            structured_llm = llm.with_structured_output(GeneratedItinerarySchema)
            prompt = (
                f"You are the TripCrew Chief Itinerary Architect. Create a logical, realistic {days}-day itinerary "
                f"for a group of {group_size} travelers visiting {destination} from {origin}.\n"
                f"Trip Pace: {pace}\n"
                f"Interests: {', '.join(interests) if interests else 'Beaches, Culture, Good Food'}\n"
                f"Must Haves: {', '.join(must_haves) if must_haves else 'Scenic highlights'}\n\n"
                "Requirements:\n"
                "1. Generate day plans for Day 1 through Day {days}.\n"
                "2. Realistic daily activity pacing (2-3 key activities per day with accurate time slots and locations).\n"
                "3. Include realistic travel gaps (e.g. '25 min coastal drive').\n"
                "4. Provide a clear 'day_rationale' for each day explaining how it fits their pace and interests.\n"
            )
            result = structured_llm.invoke(prompt)
            if result and result.days:
                itinerary_days = result.days
        except Exception:
            itinerary_days = None

    if not itinerary_days:
        itinerary_days = _generate_destination_itinerary(
            destination=destination,
            days=days,
            group_size=group_size,
            pace=pace,
            interests=interests,
            origin=origin,
        )

    return {
        "itinerary": itinerary_days,
        "status": "in_progress",
    }


# ============================================================================
# AGENT 3: BUDGET AGENT
# ============================================================================

def _load_rate_sheet_data(destination: str) -> Dict[str, Dict[str, Any]]:
    """
    Reads data/rate_sheet.csv and matches rates for the destination and tiers.
    Falls back to 'Default' or 'Goa' if destination is not explicitly listed.
    """
    base_dir = Path(__file__).resolve().parent
    csv_path = base_dir / "data" / "rate_sheet.csv"

    rates_by_tier: Dict[str, Dict[str, Any]] = {}
    fallback_rates: Dict[str, Dict[str, Any]] = {}

    if not csv_path.exists():
        # Built-in fallback rates if CSV is missing
        return {
            "Budget": {
                "hotel_name": "Standard 3-Star Boutique Hotel",
                "hotel_cost_per_room_night": 2200.0,
                "transfer_type": "Shared AC Sedan & Local Cabs",
                "transfer_cost_per_day": 1200.0,
                "activity_description": "Essential walking tours & beach exploration",
                "activity_cost_per_person_day": 800.0,
            },
            "Standard": {
                "hotel_name": "4-Star Beach Resort & Swimming Pool",
                "hotel_cost_per_room_night": 5500.0,
                "transfer_type": "Dedicated Private AC SUV (Ertiga / Innova)",
                "transfer_cost_per_day": 2800.0,
                "activity_description": "Water sports combo & sunset river cruise",
                "activity_cost_per_person_day": 2200.0,
            },
            "Premium": {
                "hotel_name": "5-Star Luxury Beach Villa & Heritage Estate",
                "hotel_cost_per_room_night": 14500.0,
                "transfer_type": "Private Chauffeur Luxury SUV (Fortuner / BMW)",
                "transfer_cost_per_day": 6000.0,
                "activity_description": "Private catamaran charter & curated Chef's Table dining",
                "activity_cost_per_person_day": 5500.0,
            },
        }

    dest_clean = (destination or "Goa").strip().lower()

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_dest = row["destination"].strip().lower()
            tier = row["tier"].strip()
            data_dict = {
                "hotel_name": row["hotel_name"],
                "hotel_cost_per_room_night": float(row["hotel_cost_per_room_night"]),
                "transfer_type": row["transfer_type"],
                "transfer_cost_per_day": float(row["transfer_cost_per_day"]),
                "activity_description": row["activities_description"],
                "activity_cost_per_person_day": float(row["activity_cost_per_person_day"]),
            }

            if row_dest == "default" or row_dest == "goa":
                fallback_rates[tier] = data_dict

            if row_dest in dest_clean or dest_clean in row_dest:
                rates_by_tier[tier] = data_dict

    # If destination specific match wasn't fully found, fill with fallback
    for t in ["Budget", "Standard", "Premium"]:
        if t not in rates_by_tier and t in fallback_rates:
            rates_by_tier[t] = fallback_rates[t]

    return rates_by_tier


def budget_agent(state: TripBrief) -> Dict[str, Any]:
    """
    Budget Agent Node:
    1. Loads rate sheet items for destination.
    2. Computes room count (double occupancy).
    3. Calculates base costs across hotel nights, daily transfers, and daily activities.
    4. Applies agency margin (15%).
    5. Calculates per-person quote and total quote.
    6. Compares with client target budget.
    """
    destination = state.trip_basics.destination or "Goa"
    group_size = max(1, state.trip_basics.group_size or 4)
    nights = max(1, state.trip_basics.duration_nights or 4)
    days = max(1, state.trip_basics.duration_days or (nights + 1))
    target_budget_pp = state.budget.target_budget_per_person or 0.0

    # Double occupancy room allocation
    rooms_count = math.ceil(group_size / 2)
    agency_margin_pct = 15.0

    rates = _load_rate_sheet_data(destination)

    tier_quotes: Dict[str, TierQuote] = {}
    tier_taglines = {
        "Budget": "Essential comfort, top-rated boutique hostels/guesthouses, and self-guided discovery.",
        "Standard": "Handpicked 4-star beach resort, private dedicated SUV, and marquee guided tours.",
        "Premium": "Exclusive 5-star private pool villa, chauffeured luxury transport, and private catamaran charter.",
    }
    tier_highlights = {
        "Budget": [
            "Centrally located 3-star boutique stay",
            "Group-friendly shared airport and city transfers",
            "Self-guided heritage walks & beach shack vouchers",
            "24/7 TripCrew digital concierge",
        ],
        "Standard": [
            "4-Star beach resort with pool & daily breakfast",
            "Exclusive private AC SUV at disposal",
            "Pre-booked water sports adventure & river cruise",
            "Dedicated on-ground TripCrew trip coordinator",
        ],
        "Premium": [
            "5-Star private luxury pool villa or heritage estate",
            "Private chauffeur luxury vehicle at 24/7 disposal",
            "Private sunset catamaran charter with champagne",
            "Curated Chef's Table private beachfront dinner",
            "VIP priority reservations and personal butler",
        ],
    }

    for tier_name in ["Budget", "Standard", "Premium"]:
        tier_data = rates.get(tier_name)
        if not tier_data:
            continue

        hotel_total = tier_data["hotel_cost_per_room_night"] * rooms_count * nights
        transfers_total = tier_data["transfer_cost_per_day"] * days
        activities_total = tier_data["activity_cost_per_person_day"] * group_size * days

        subtotal_base = hotel_total + transfers_total + activities_total
        margin_amt = round(subtotal_base * (agency_margin_pct / 100.0), 2)
        grand_total = round(subtotal_base + margin_amt, 2)
        total_pp = round(grand_total / group_size, 2)

        # Budget comparison note
        if target_budget_pp > 0:
            diff = target_budget_pp - total_pp
            if diff >= 0:
                comp_note = f"Well within budget (₹{abs(diff):,.0f} savings per person vs your ₹{target_budget_pp:,.0f} target)."
            else:
                comp_note = f"₹{abs(diff):,.0f} above target per person for enhanced tier luxury."
        else:
            comp_note = f"Competitive rate of ₹{total_pp:,.0f} per person all-inclusive."

        breakdown = TierCostBreakdown(
            rooms_count=rooms_count,
            hotel_name=tier_data["hotel_name"],
            hotel_cost_per_room_night=tier_data["hotel_cost_per_room_night"],
            hotel_total_cost=hotel_total,
            transfer_type=tier_data["transfer_type"],
            transfer_cost_per_day=tier_data["transfer_cost_per_day"],
            transfers_total_cost=transfers_total,
            activity_description=tier_data["activity_description"],
            activity_cost_per_person_day=tier_data["activity_cost_per_person_day"],
            activities_total_cost=activities_total,
            subtotal_base_cost=subtotal_base,
            agency_margin_pct=agency_margin_pct,
            agency_margin_amount=margin_amt,
            grand_total_group_cost=grand_total,
            total_quote_per_person=total_pp,
            budget_comparison_note=comp_note,
        )

        tier_quotes[tier_name.lower()] = TierQuote(
            tier_name=tier_name,
            tier_tagline=tier_taglines[tier_name],
            breakdown=breakdown,
            highlights=tier_highlights[tier_name],
        )

    quotes_summary = QuotesSummary(
        currency="INR",
        agency_margin_pct=agency_margin_pct,
        budget_tier=tier_quotes.get("budget"),
        standard_tier=tier_quotes.get("standard"),
        premium_tier=tier_quotes.get("premium"),
    )

    return {
        "quotes": quotes_summary,
        "status": "in_progress",
    }


# ============================================================================
# AGENT 4: DOCUMENT AGENT (PDF GENERATION)
# ============================================================================

def document_agent(state: TripBrief) -> Dict[str, Any]:
    """
    Document Agent Node:
    Compiles client information, itinerary, and tiered quotes into an executive-grade,
    branded PDF proposal using reportlab.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        KeepTogether,
        HRFlowable,
    )

    base_dir = Path(__file__).resolve().parent
    quotes_dir = base_dir / "generated_quotes"
    quotes_dir.mkdir(parents=True, exist_ok=True)

    dest = state.trip_basics.destination or "Vacation"
    clean_dest = re.sub(r"[^\w\-]", "_", dest)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"TripCrew_Quote_{clean_dest}_{timestamp}.pdf"
    pdf_full_path = str(quotes_dir / filename)

    doc = SimpleDocTemplate(
        pdf_full_path,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom Color Palette
    PRIMARY_COLOR = colors.HexColor("#0F172A")    # Deep Slate / Charcoal
    TEAL_ACCENT = colors.HexColor("#0D9488")      # TripCrew Emerald / Teal
    LIGHT_BG = colors.HexColor("#F8FAFC")         # Off-white / Slate 50
    CARD_BG = colors.HexColor("#F1F5F9")          # Slate 100
    BORDER_COLOR = colors.HexColor("#CBD5E1")     # Slate 300
    TEXT_MUTED = colors.HexColor("#64748B")       # Slate 500
    GOLD_ACCENT = colors.HexColor("#B45309")      # Amber / Gold

    # Custom Typography Styles
    brand_style = ParagraphStyle(
        "BrandHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=24,
        leading=28,
        textColor=PRIMARY_COLOR,
    )

    tagline_style = ParagraphStyle(
        "BrandTagline",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=TEAL_ACCENT,
    )

    h1_style = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=PRIMARY_COLOR,
        spaceBefore=14,
        spaceAfter=8,
    )

    body_style = ParagraphStyle(
        "BodyDark",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=13.5,
        textColor=PRIMARY_COLOR,
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=TEXT_MUTED,
    )

    meta_val_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=PRIMARY_COLOR,
    )

    table_header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=12,
        textColor=colors.white,
        alignment=1,  # Center
    )

    table_cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=PRIMARY_COLOR,
    )

    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11.5,
        textColor=PRIMARY_COLOR,
    )

    table_cell_price = ParagraphStyle(
        "TableCellPrice",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=13,
        textColor=TEAL_ACCENT,
        alignment=1,
    )

    story = []

    # 1. HEADER BANNER
    header_table_data = [
        [
            Paragraph("TRIPCREW <font color='#0D9488'>AI</font>", brand_style),
            Paragraph(f"<b>QUOTE REFERENCE:</b> TC-{timestamp[:8]}<br/><b>DATE:</b> {datetime.now().strftime('%B %d, %Y')}<br/><b>STATUS:</b> Confirmed Proposal", meta_label_style),
        ],
        [
            Paragraph("AI-Powered Curated Travel Engineering & Quotation", tagline_style),
            "",
        ]
    ]
    header_table = Table(header_table_data, colWidths=[340, 200])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=2, color=TEAL_ACCENT, spaceBefore=4, spaceAfter=14))

    # 2. TRIP BASICS SUMMARY CARD
    basics = state.trip_basics
    client = state.client
    budget = state.budget

    origin_str = basics.origin or "Not specified"
    dest_str = basics.destination or "Destination"
    dates_str = basics.travel_dates or f"{basics.duration_days or 5} Days Trip"
    duration_str = f"{basics.duration_days or 5} Days / {basics.duration_nights or 4} Nights"
    group_str = f"{basics.group_size or 4} Travelers"
    target_budget_str = f"₹{budget.target_budget_per_person:,.0f} / person" if budget.target_budget_per_person else "Standard"

    overview_data = [
        [
            Paragraph("CLIENT NAME", meta_label_style),
            Paragraph("DESTINATION ROUTE", meta_label_style),
            Paragraph("DURATION & DATES", meta_label_style),
            Paragraph("GROUP & PACE", meta_label_style),
            Paragraph("TARGET BUDGET", meta_label_style),
        ],
        [
            Paragraph(client.name or "Valued Client", meta_val_style),
            Paragraph(f"{origin_str} &rarr; {dest_str}", meta_val_style),
            Paragraph(f"{duration_str}<br/><font size=8 color='#64748B'>{dates_str}</font>", meta_val_style),
            Paragraph(f"{group_str}<br/><font size=8 color='#64748B'>{state.preferences_and_constraints.pace} Pace</font>", meta_val_style),
            Paragraph(target_budget_str, meta_val_style),
        ],
    ]
    overview_table = Table(overview_data, colWidths=[105, 120, 115, 105, 95])
    overview_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), LIGHT_BG),
        ('BOX', (0,0), (-1,-1), 1, BORDER_COLOR),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 14))

    # 3. TIERED PRICING COMPARISON TABLE
    story.append(Paragraph("Tiered Pricing & Investment Breakdown", h1_style))
    story.append(Paragraph("All quotes include verified local vendor unit rates, ground logistics, activities, and TripCrew's transparent 15% agency management margin.", body_style))
    story.append(Spacer(1, 8))

    q = state.quotes
    b_tier = q.budget_tier if q else None
    s_tier = q.standard_tier if q else None
    p_tier = q.premium_tier if q else None

    def get_tier_val(tier: Optional[TierQuote], field: str, default: str = "-") -> str:
        if not tier:
            return default
        br = tier.breakdown
        if field == "hotel":
            return f"<b>{br.hotel_name}</b><br/><font color='#64748B'>{br.rooms_count} rooms &times; ₹{br.hotel_cost_per_room_night:,.0f}/nt</font>"
        elif field == "transfers":
            return f"<b>{br.transfer_type}</b><br/><font color='#64748B'>Daily ₹{br.transfer_cost_per_day:,.0f}</font>"
        elif field == "activities":
            return f"<b>{br.activity_description}</b><br/><font color='#64748B'>₹{br.activity_cost_per_person_day:,.0f}/person/day</font>"
        elif field == "subtotal":
            return f"₹{br.subtotal_base_cost:,.0f}"
        elif field == "margin":
            return f"₹{br.agency_margin_amount:,.0f} (15%)"
        elif field == "total_group":
            return f"<b>₹{br.grand_total_group_cost:,.0f}</b>"
        elif field == "per_person":
            return f"<b>₹{br.total_quote_per_person:,.0f}</b>"
        elif field == "comparison":
            return f"<font color='#0D9488'>{br.budget_comparison_note or ''}</font>"
        return default

    pricing_headers = [
        Paragraph("Package Component", table_header_style),
        Paragraph("Budget Tier", table_header_style),
        Paragraph("Standard Tier (Recommended)", table_header_style),
        Paragraph("Premium Tier", table_header_style),
    ]

    pricing_rows = [
        pricing_headers,
        [
            Paragraph("Accommodation", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "hotel"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "hotel"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "hotel"), table_cell_style),
        ],
        [
            Paragraph("Ground Transfers", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "transfers"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "transfers"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "transfers"), table_cell_style),
        ],
        [
            Paragraph("Curated Activities", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "activities"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "activities"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "activities"), table_cell_style),
        ],
        [
            Paragraph("Net Base Cost (Group)", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "subtotal"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "subtotal"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "subtotal"), table_cell_style),
        ],
        [
            Paragraph("Agency Margin (15%)", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "margin"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "margin"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "margin"), table_cell_style),
        ],
        [
            Paragraph("Total Group Investment", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "total_group"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "total_group"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "total_group"), table_cell_style),
        ],
        [
            Paragraph("FINAL QUOTE / PERSON", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "per_person"), table_cell_price),
            Paragraph(get_tier_val(s_tier, "per_person"), table_cell_price),
            Paragraph(get_tier_val(p_tier, "per_person"), table_cell_price),
        ],
        [
            Paragraph("Budget Analysis", table_cell_bold),
            Paragraph(get_tier_val(b_tier, "comparison"), table_cell_style),
            Paragraph(get_tier_val(s_tier, "comparison"), table_cell_style),
            Paragraph(get_tier_val(p_tier, "comparison"), table_cell_style),
        ],
    ]

    pricing_table = Table(pricing_rows, colWidths=[120, 135, 150, 135])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), PRIMARY_COLOR),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_BG]),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        # Highlight Recommended Tier Column (Col 2)
        ('BACKGROUND', (2,1), (2,-1), colors.HexColor("#F0FDFA")),
        ('BOX', (2,0), (2,-1), 1.5, TEAL_ACCENT),
        # Highlight Final Quote Row (Row 7)
        ('BACKGROUND', (0,7), (-1,7), colors.HexColor("#E2E8F0")),
    ]))
    story.append(pricing_table)
    story.append(Spacer(1, 16))

    # 4. DAY-BY-DAY ITINERARY
    story.append(Paragraph("Day-by-Day Curated Itinerary", h1_style))
    story.append(Paragraph("Carefully balanced timetable accounting for travel distances, relaxation, and peak experience timings.", body_style))
    story.append(Spacer(1, 8))

    for day in state.itinerary:
        day_block = []

        day_title_style = ParagraphStyle(
            f"DayTitle_{day.day_number}",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=PRIMARY_COLOR,
        )

        day_rationale_style = ParagraphStyle(
            f"DayRationale_{day.day_number}",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11.5,
            textColor=TEXT_MUTED,
        )

        # Day Header Box
        day_header_data = [
            [
                Paragraph(f"<b>{day.title}</b>", day_title_style),
            ],
            [
                Paragraph(f"<b>Pacing & Strategy:</b> {day.day_rationale}", day_rationale_style),
            ]
        ]
        day_header_table = Table(day_header_data, colWidths=[540])
        day_header_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), CARD_BG),
            ('BOX', (0,0), (-1,-1), 0.75, BORDER_COLOR),
            ('LINELEFT', (0,0), (0,-1), 3, TEAL_ACCENT),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ]))
        day_block.append(day_header_table)
        day_block.append(Spacer(1, 4))

        # Activities Table for this day
        act_rows = [
            [
                Paragraph("Timing", table_header_style),
                Paragraph("Activity & Inclusions", table_header_style),
                Paragraph("Location", table_header_style),
                Paragraph("Travel Gap", table_header_style),
            ]
        ]

        for act in day.activities:
            act_rows.append([
                Paragraph(f"<b>{act.time_slot}</b>", table_cell_bold),
                Paragraph(f"<b>{act.title}</b><br/><font color='#334155'>{act.description}</font>", table_cell_style),
                Paragraph(act.location or "-", table_cell_style),
                Paragraph(f"<font color='#0D9488'>{act.estimated_travel_gap or 'Direct'}</font>", table_cell_style),
            ])

        act_table = Table(act_rows, colWidths=[90, 260, 100, 90])
        act_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), PRIMARY_COLOR),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('GRID', (0,0), (-1,-1), 0.5, BORDER_COLOR),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, LIGHT_BG]),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ('LEFTPADDING', (0,0), (-1,-1), 5),
            ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ]))
        day_block.append(act_table)
        day_block.append(Spacer(1, 10))

        story.append(KeepTogether(day_block))

    # 5. INCLUSIONS & BOOKING TERMS
    terms_block = [
        Spacer(1, 8),
        Paragraph("TripCrew Service Guarantees & Booking Policies", h1_style),
        Paragraph(
            "&bull; <b>What's Included:</b> All listed accommodations, dedicated ground transit vehicles with commercial permits, driver allowances, entry permits, and booked experiences.<br/>"
            "&bull; <b>Agency Guarantee:</b> 100% price transparency with no hidden markups. 24/7 digital concierge support via WhatsApp.<br/>"
            "&bull; <b>To Confirm Booking:</b> Reply to this quote or approve via your TripCrew portal with a 25% refundable deposit.",
            body_style,
        ),
        Spacer(1, 10),
        Paragraph(
            "<font color='#64748B'>TripCrew Travel Technologies Pvt Ltd &bull; Confidential Proposal &bull; Valid for 7 Days</font>",
            meta_label_style,
        )
    ]
    story.append(KeepTogether(terms_block))

    # Build the document
    doc.build(story)

    return {
        "pdf_path": pdf_full_path,
        "pdf_filename": filename,
        "status": "completed",
    }
