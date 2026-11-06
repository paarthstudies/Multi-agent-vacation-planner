"""
TripCrew Backend Platform - Phase 1 MVP
FastAPI Application and Public REST Endpoints
"""

import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import InquiryRequest, InquiryResponse, TripBrief
from graph import run_inquiry_pipeline

# Initialize FastAPI application
app = FastAPI(
    title="TripCrew Vacation Planner API",
    description="Multi-Agent LangGraph Backend for AI-powered Vacation Planning and Quotation",
    version="1.0.0",
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
    """Ensures rate sheets and quotes directory exist at app startup."""
    QUOTES_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    csv_file = DATA_DIR / "rate_sheet.csv"
    if not csv_file.exists():
        sample_csv = (
            "destination,tier,hotel_name,hotel_cost_per_room_night,transfer_type,transfer_cost_per_day,activities_description,activity_cost_per_person_day\n"
            "Goa,Budget,Zostel / Heritage Guesthouse Calangute,2200,Shared AC Cabs / Self-drive Scooters,1200,Beach exploration & Old Goa church heritage walk,800\n"
            "Goa,Standard,4-Star North Goa Boutique Beach Resort,5500,Dedicated Private AC SUV (Ertiga / Innova),2800,Water sports combo at Calangute & Mandovi sunset cruise,2200\n"
            "Goa,Premium,5-Star Luxury Beach Villa & Heritage Estate,14500,Private Chauffeur Luxury Car / Fortuner,6000,Private catamaran charter & curated Chef's Table dining,5500\n"
            "Jaipur,Budget,Heritage Haveli & Boutique Guesthouse,2000,Standard AC Sedan City Car,1400,Amber Fort & Old City Bazaar walking tour,700\n"
            "Jaipur,Standard,4-Star Royal Heritage Haveli Resort,5000,Private AC Ertiga/Innova,2600,Nahargarh sunset tour & cultural puppet dinner show,2000\n"
            "Jaipur,Premium,5-Star Palace Hotel & Spa,16000,Chauffeured Luxury Car,6500,Hot air balloon ride & private royal palace banquet,6000\n"
            "Kerala,Budget,Backwater Homestay & Eco Cottages,2400,Standard AC Sedan,1500,Village canoe ride & Kathakali dance show,900\n"
            "Kerala,Standard,4-Star Backwater Lagoon Resort,6000,Private AC SUV,3000,Alleppey Houseboat day cruise & spice plantation tour,2400\n"
            "Kerala,Premium,5-Star Luxury Ayurveda & Lakefront Villa,15000,Chauffeured Luxury Car,6200,Private overnight luxury houseboat & Ayurvedic spa rituals,5800\n"
            "Manali,Budget,Riverside Cabin & Apple Orchard Stay,2000,Standard AC Hatchback,1600,Solang valley nature walk & Old Manali cafes,800\n"
            "Manali,Standard,4-Star Mountain View Resort & Spa,5200,Private 4x4 SUV,3200,Rohtang pass excursion & paragliding combo,2500\n"
            "Manali,Premium,5-Star Luxury Pine Chalet & Heated Pool,13500,Luxury Chauffeured SUV,6000,Private mountain excursion & gourmet barbecue bonfire,5200\n"
            "Default,Budget,Standard 3-Star City Hotel / Boutique Stay,2200,Standard AC Sedan Transfers,1300,Essential city highlights & self-guided walking tours,800\n"
            "Default,Standard,4-Star Premium Resort & City Center Hotel,5500,Dedicated Private SUV,2800,Curated guided excursions & cultural evening events,2200\n"
            "Default,Premium,5-Star Signature Luxury Resort & Private Villas,14500,Chauffeured Luxury Vehicle,6000,VIP access & private chartered experiences,5500\n"
        )
        with open(csv_file, "w", encoding="utf-8") as f:
            f.write(sample_csv)


@app.on_event("startup")
async def startup_event():
    ensure_startup_resources()


@app.get("/")
def read_root():
    return {
        "service": "TripCrew Vacation Planner API",
        "version": "1.0.0",
        "status": "online",
        "documentation": "/docs",
        "endpoints": {
            "inquiry": "POST /api/v1/inquiry",
            "download_quote": "GET /api/v1/quotes/{filename}",
        },
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "rate_sheet_present": (DATA_DIR / "rate_sheet.csv").exists(),
        "quotes_directory_present": QUOTES_DIR.exists(),
    }


@app.post("/api/v1/inquiry", response_model=InquiryResponse)
async def process_inquiry(req: InquiryRequest, request: Request):
    """
    Main Vacation Planning Endpoint:
    Accepts an unstructured chat inquiry, executes the LangGraph agent state machine,
    and returns either a clarification question or the structured itinerary, tiered quotes,
    and generated PDF download URL.
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

        # Check for completion
        if trip_brief.status == "completed":
            download_url = None
            if trip_brief.pdf_filename:
                # Dynamic base url
                base_url = str(request.base_url).rstrip("/")
                download_url = f"{base_url}/api/v1/quotes/{trip_brief.pdf_filename}"

            return InquiryResponse(
                status="completed",
                trip_brief=trip_brief,
                pdf_download_url=download_url,
                pdf_file_path=trip_brief.pdf_path,
            )

        # Fallback response for other statuses
        return InquiryResponse(
            status=trip_brief.status,
            trip_brief=trip_brief,
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
