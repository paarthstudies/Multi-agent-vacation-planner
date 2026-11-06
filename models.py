"""
TripCrew Backend Platform - Phase 1 MVP
Data Models and Shared State Schema (TripBrief)
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ClientInfo(BaseModel):
    name: Optional[str] = Field(default="Valued Traveler", description="Client name")
    contact: Optional[str] = Field(default=None, description="Phone, email, or handle")
    preferred_language: str = Field(default="English", description="Communication language preference")
    channel: str = Field(default="chat", description="Inquiry source channel (chat, whatsapp, web)")


class TripBasics(BaseModel):
    origin: Optional[str] = Field(default=None, description="Departure city or airport")
    destination: Optional[str] = Field(default=None, description="Destination city/region")
    travel_dates: Optional[str] = Field(default=None, description="Approximate or exact travel dates")
    duration_days: Optional[int] = Field(default=None, description="Total duration of trip in days")
    duration_nights: Optional[int] = Field(default=None, description="Total nights of accommodation")
    group_size: Optional[int] = Field(default=None, description="Number of traveling guests")


class BudgetConstraint(BaseModel):
    target_budget_per_person: Optional[float] = Field(
        default=None, description="Customer stated target budget per person"
    )
    total_target_budget: Optional[float] = Field(
        default=None, description="Total aggregate budget for the entire group"
    )
    currency: str = Field(default="INR", description="Currency symbol/code (INR, USD, etc.)")


class PreferencesAndConstraints(BaseModel):
    pace: Optional[str] = Field(
        default="Moderate", description="Trip pacing: Relaxed, Moderate, or Active/Fast-paced"
    )
    dietary_requirements: List[str] = Field(
        default_factory=list, description="Dietary preferences (Vegetarian, Vegan, Halal, Jain, etc.)"
    )
    must_haves: List[str] = Field(
        default_factory=list, description="Explicit must-haves or activities requested"
    )
    interests: List[str] = Field(
        default_factory=list, description="General interests (e.g., beaches, heritage, nightlife, food)"
    )


class ActivityItem(BaseModel):
    time_slot: str = Field(..., description="Time slot or phase of day (e.g., '09:00 - 11:30 AM' or 'Morning')")
    title: str = Field(..., description="Concise activity title")
    description: str = Field(..., description="Detailed description of the activity")
    location: Optional[str] = Field(default=None, description="Specific location or attraction")
    estimated_travel_gap: Optional[str] = Field(
        default=None, description="Travel gap or commute time from previous location"
    )


class DayPlan(BaseModel):
    day_number: int = Field(..., description="Day index (1, 2, ...)")
    title: str = Field(..., description="Catchy theme or title for the day")
    summary: str = Field(..., description="High-level overview of the day's schedule")
    activities: List[ActivityItem] = Field(default_factory=list, description="Sequential activities")
    day_rationale: str = Field(
        ..., description="Brief rationale connecting the schedule to customer pace and preferences"
    )


class TierCostBreakdown(BaseModel):
    rooms_count: int = Field(..., description="Number of hotel rooms allocated based on group size")
    hotel_name: str = Field(..., description="Name or description of accommodation")
    hotel_cost_per_room_night: float = Field(..., description="Base rate per room night")
    hotel_total_cost: float = Field(..., description="Total accommodation cost across all rooms and nights")

    transfer_type: str = Field(..., description="Mode of ground transportation")
    transfer_cost_per_day: float = Field(..., description="Daily transfer base rate")
    transfers_total_cost: float = Field(..., description="Total ground transport cost")

    activity_description: str = Field(..., description="Activities and experiences included")
    activity_cost_per_person_day: float = Field(..., description="Daily activities cost per traveler")
    activities_total_cost: float = Field(..., description="Total activities and experience cost")

    subtotal_base_cost: float = Field(..., description="Net cost before agency margin")
    agency_margin_pct: float = Field(default=15.0, description="Agency markup percentage")
    agency_margin_amount: float = Field(..., description="Agency markup amount")
    grand_total_group_cost: float = Field(..., description="Total quote for the entire group including margin")
    total_quote_per_person: float = Field(..., description="Final price per traveler including margin")
    budget_comparison_note: Optional[str] = Field(
        default=None, description="Analysis against the customer's target budget"
    )


class TierQuote(BaseModel):
    tier_name: str = Field(..., description="'Budget', 'Standard', or 'Premium'")
    tier_tagline: str = Field(..., description="Short value proposition")
    breakdown: TierCostBreakdown
    highlights: List[str] = Field(default_factory=list, description="Perks and inclusions in this tier")


class QuotesSummary(BaseModel):
    currency: str = Field(default="INR", description="Pricing currency")
    agency_margin_pct: float = Field(default=15.0, description="Standard agency margin applied")
    budget_tier: Optional[TierQuote] = None
    standard_tier: Optional[TierQuote] = None
    premium_tier: Optional[TierQuote] = None


class TripBrief(BaseModel):
    """
    TripBrief is the central shared state model passed through all LangGraph nodes.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # Raw user inputs & metadata
    raw_inquiry: str = Field(default="", description="Original customer chat input")
    session_id: Optional[str] = Field(default=None, description="Session or conversation tracking ID")

    # Structured domains
    client: ClientInfo = Field(default_factory=ClientInfo)
    trip_basics: TripBasics = Field(default_factory=TripBasics)
    budget: BudgetConstraint = Field(default_factory=BudgetConstraint)
    preferences_and_constraints: PreferencesAndConstraints = Field(default_factory=PreferencesAndConstraints)

    # Generated itinerary & quotes
    itinerary: List[DayPlan] = Field(default_factory=list, description="Day-by-day plan")
    quotes: Optional[QuotesSummary] = Field(default=None, description="Tiered pricing quotes")

    # Execution state machine
    status: str = Field(
        default="initialized",
        description="Current state: 'initialized', 'needs_clarification', 'in_progress', 'completed', 'failed'",
    )
    missing_fields: List[str] = Field(
        default_factory=list, description="List of required fields missing from inquiry"
    )
    clarification_question: Optional[str] = Field(
        default=None, description="Generated clarifying prompt for the customer"
    )
    pdf_path: Optional[str] = Field(default=None, description="Local absolute path to generated PDF quote")
    pdf_filename: Optional[str] = Field(default=None, description="Filename for web downloads")
    error_message: Optional[str] = Field(default=None, description="Error details if execution fails")


# API Schemas
class InquiryRequest(BaseModel):
    message: str = Field(..., description="Unstructured customer inquiry", min_length=3)
    client_name: Optional[str] = Field(default="Valued Traveler")
    contact: Optional[str] = Field(default=None)
    session_id: Optional[str] = Field(default=None)


class InquiryResponse(BaseModel):
    status: str
    question: Optional[str] = None
    missing_fields: Optional[List[str]] = None
    trip_brief: Optional[TripBrief] = None
    pdf_download_url: Optional[str] = None
    pdf_file_path: Optional[str] = None
    error: Optional[str] = None
