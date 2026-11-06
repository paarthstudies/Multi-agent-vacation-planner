"""
TripCrew Backend Platform - Phase 2 (Quality)
FastAPI Application and Public REST Endpoints
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from models import InquiryRequest, InquiryResponse, TripBrief
from graph import run_inquiry_pipeline
from services import maps_service, weather_service, pricing_service

# Initialize FastAPI application
app = FastAPI(
    title="TripCrew Vacation Planner API - Phase 2 (Quality)",
    description="Multi-Agent LangGraph Backend with Critic Validator Node, Live Travel APIs, and Automated Re-planning Loop",
    version="2.0.0",
)

# Enable CORS for web and client integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
QUOTES_DIR = BASE_DIR / "generated_quotes"


def ensure_startup_resources():
    """Ensures directories exist at app startup."""
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


@app.on_event("startup")
async def startup_event():
    ensure_startup_resources()


@app.get("/")
def read_root():
    return {
        "service": "TripCrew Vacation Planner API",
        "phase": "Phase 2 (Quality)",
        "version": "2.0.0",
        "status": "online",
        "quality_gates": {
            "validator_critic_node": "active",
            "re_planning_loop": "active (max 3 retries)",
            "live_integrations": ["Google Maps / Places", "OpenWeather", "Amadeus / Flight & Hotel Sandbox"],
        },
        "documentation": "/docs",
        "endpoints": {
            "inquiry": "POST /api/v1/inquiry",
            "download_quote": "GET /api/v1/quotes/{filename}",
            "health": "GET /health",
        },
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "integrations": {
            "google_maps": "live" if maps_service.api_key else "gis_sandbox_active",
            "openweather": "live" if weather_service.api_key else "climatology_sandbox_active",
            "travel_pricing": "amadeus_live" if (pricing_service.client_id and pricing_service.client_secret) else "dynamic_sandbox_active",
        },
        "quotes_directory_present": QUOTES_DIR.exists(),
    }


@app.post("/api/v1/inquiry", response_model=InquiryResponse)
async def process_inquiry(req: InquiryRequest, request: Request):
    """
    Main Vacation Planning Endpoint:
    Accepts an unstructured chat inquiry, executes the LangGraph agent state machine
    with the Critic Validator quality loop, and returns either a clarification question
    or the validated itinerary, tiered quotes, quality feasibility score, and PDF quote URL.
    """
    try:
        trip_brief = run_inquiry_pipeline(
            raw_message=req.message,
            session_id=req.session_id,
            client_name=req.client_name,
            contact=req.contact,
        )

        # Check if graph halted because of missing mandatory fields
        if trip_brief.status == "needs_clarification":
            return InquiryResponse(
                status="needs_clarification",
                question=trip_brief.clarification_question,
                missing_fields=trip_brief.missing_fields,
                trip_brief=trip_brief,
            )

        # Compile validation summary
        validation_dict: Optional[Dict[str, Any]] = None
        if trip_brief.validation_result:
            vr = trip_brief.validation_result
            validation_dict = {
                "is_valid": vr.is_valid,
                "feasibility_score": vr.feasibility_score,
                "replan_count": trip_brief.replan_count,
                "pillars": {
                    "opening_hours": vr.opening_hours_passed,
                    "travel_logistics": vr.travel_logistics_passed,
                    "budget": vr.budget_passed,
                    "visa_rules": vr.visa_rules_passed,
                },
                "issues_detected": len(vr.issues),
            }

        # Check for completion
        if trip_brief.status == "completed":
            download_url = None
            if trip_brief.pdf_filename:
                base_url = str(request.base_url).rstrip("/")
                download_url = f"{base_url}/api/v1/quotes/{trip_brief.pdf_filename}"

            return InquiryResponse(
                status="completed",
                trip_brief=trip_brief,
                validation_summary=validation_dict,
                pdf_download_url=download_url,
                pdf_file_path=trip_brief.pdf_path,
            )

        # Fallback response for other statuses
        return InquiryResponse(
            status=trip_brief.status,
            trip_brief=trip_brief,
            validation_summary=validation_dict,
            question=trip_brief.clarification_question,
            missing_fields=trip_brief.missing_fields,
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "status": "failed",
                "error": str(e),
            },
        )


@app.get("/api/v1/quotes/{filename}")
async def download_quote_pdf(filename: str):
    """
    Serves the locally generated PDF quote document.
    """
    file_path = QUOTES_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Requested quote document does not exist.")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=filename,
    )


if __name__ == "__main__":
    import uvicorn
    ensure_startup_resources()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
