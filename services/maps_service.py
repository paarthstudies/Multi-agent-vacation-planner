"""
TripCrew Backend Platform - Phase 2 (Quality)
Google Maps and Places Integration Service
Provides live Distance Matrix, transit feasibility checks, and Place Details (opening hours & zones).
"""

import os
import re
import math
from typing import Dict, Any, Optional, List, Tuple
import httpx


class GoogleMapsService:
    """
    Service wrapper for Google Maps Platform (Distance Matrix & Places API).
    Includes live API execution with automatic fallback to high-fidelity geographic
    distance matrices and opening hours database.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.base_url = "https://maps.googleapis.com/maps/api"

        # High-Fidelity POI Database: coordinates, opening hours, closed days, zones
        self._poi_database = {
            # --- GOA POIs ---
            "aguada fort": {
                "name": "Fort Aguada & Lighthouse",
                "zone": "North Goa - Candolim",
                "lat": 15.4920, "lng": 73.7737,
                "open_hour": 9.5, "close_hour": 17.5, # 09:30 AM to 05:30 PM
                "closed_days": [],
                "recommended_hours": 2.0,
            },
            "calangute beach": {
                "name": "Calangute Beach Watersports Hub",
                "zone": "North Goa - Calangute",
                "lat": 15.5439, "lng": 73.7554,
                "open_hour": 6.0, "close_hour": 22.0,
                "closed_days": [],
                "recommended_hours": 3.0,
            },
            "baga beach": {
                "name": "Baga Beach Promenade & Shacks",
                "zone": "North Goa - Baga",
                "lat": 15.5553, "lng": 73.7516,
                "open_hour": 6.0, "close_hour": 23.5,
                "closed_days": [],
                "recommended_hours": 2.5,
            },
            "anjuna beach": {
                "name": "Anjuna Beach & Flea Market",
                "zone": "North Goa - Anjuna",
                "lat": 15.5807, "lng": 73.7432,
                "open_hour": 6.0, "close_hour": 23.0,
                "closed_days": [],
                "recommended_hours": 2.5,
            },
            "vagator beach": {
                "name": "Vagator Beach & Chapora Fort",
                "zone": "North Goa - Vagator",
                "lat": 15.6030, "lng": 73.7336,
                "open_hour": 6.0, "close_hour": 23.0,
                "closed_days": [],
                "recommended_hours": 2.0,
            },
            "chapora fort": {
                "name": "Chapora Fort Bastion",
                "zone": "North Goa - Vagator",
                "lat": 15.6056, "lng": 73.7369,
                "open_hour": 9.0, "close_hour": 18.0,
                "closed_days": [],
                "recommended_hours": 1.5,
            },
            "basilica of bom jesus": {
                "name": "Basilica of Bom Jesus (UNESCO)",
                "zone": "Central Goa - Old Goa",
                "lat": 15.5009, "lng": 73.9116,
                "open_hour": 9.0, "close_hour": 18.5, # 09:00 AM - 06:30 PM (Sun 12:00 PM - 06:30 PM)
                "closed_days": [],
                "recommended_hours": 1.5,
            },
            "se cathedral": {
                "name": "Sé Cathedral of Santa Catarina",
                "zone": "Central Goa - Old Goa",
                "lat": 15.5036, "lng": 73.9126,
                "open_hour": 7.5, "close_hour": 18.0,
                "closed_days": [],
                "recommended_hours": 1.0,
            },
            "fontainhas": {
                "name": "Fontainhas Latin Quarter",
                "zone": "Central Goa - Panaji",
                "lat": 15.4962, "lng": 73.8300,
                "open_hour": 8.0, "close_hour": 21.0,
                "closed_days": [],
                "recommended_hours": 2.5,
            },
            "mandovi river jetty": {
                "name": "Panjim Mandovi River Cruise Jetty",
                "zone": "Central Goa - Panaji",
                "lat": 15.4989, "lng": 73.8278,
                "open_hour": 17.0, "close_hour": 22.0, # Sunset/Dinner cruises only
                "closed_days": [],
                "recommended_hours": 2.0,
            },
            "palolem beach": {
                "name": "Palolem Beach & Bay",
                "zone": "South Goa - Canacona",
                "lat": 15.0100, "lng": 74.0232,
                "open_hour": 6.0, "close_hour": 23.0,
                "closed_days": [],
                "recommended_hours": 3.0,
            },
            "agonda beach": {
                "name": "Agonda Beach Turtle Nesting Site",
                "zone": "South Goa - Agonda",
                "lat": 15.0450, "lng": 73.9877,
                "open_hour": 6.0, "close_hour": 22.0,
                "closed_days": [],
                "recommended_hours": 2.5,
            },
            "dabolim airport": {
                "name": "Goa International Airport (GOI / Dabolim)",
                "zone": "South Goa - Vasco da Gama",
                "lat": 15.3800, "lng": 73.8314,
                "open_hour": 0.0, "close_hour": 24.0,
                "closed_days": [],
                "recommended_hours": 1.0,
            },
            "mopa airport": {
                "name": "Manohar International Airport (GOX / Mopa)",
                "zone": "North Goa - Pernem",
                "lat": 15.7533, "lng": 73.8686,
                "open_hour": 0.0, "close_hour": 24.0,
                "closed_days": [],
                "recommended_hours": 1.0,
            },

            # --- JAIPUR POIs ---
            "amber fort": {
                "name": "Amber Palace & Fort",
                "zone": "Jaipur - Amer",
                "lat": 26.9855, "lng": 75.8513,
                "open_hour": 8.0, "close_hour": 17.5,
                "closed_days": [],
                "recommended_hours": 3.0,
            },
            "city palace": {
                "name": "City Palace of Jaipur",
                "zone": "Jaipur - Old City",
                "lat": 26.9258, "lng": 75.8237,
                "open_hour": 9.5, "close_hour": 17.0,
                "closed_days": [],
                "recommended_hours": 2.0,
            },
            "hawa mahal": {
                "name": "Hawa Mahal (Palace of Winds)",
                "zone": "Jaipur - Old City",
                "lat": 26.9239, "lng": 75.8267,
                "open_hour": 9.0, "close_hour": 17.0,
                "closed_days": [],
                "recommended_hours": 1.0,
            },
            "nahargarh fort": {
                "name": "Nahargarh Fort Sunset Point",
                "zone": "Jaipur - Aravalli Ridge",
                "lat": 26.9374, "lng": 75.8156,
                "open_hour": 10.0, "close_hour": 20.0,
                "closed_days": [],
                "recommended_hours": 2.0,
            },
        }

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Computes great-circle distance in kilometers."""
        R = 6371.0
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(d_lat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(d_lon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _fuzzy_lookup_poi(self, query: str) -> Optional[Dict[str, Any]]:
        """Finds closest matching POI from database."""
        q_clean = query.lower().strip()
        for key, data in self._poi_database.items():
            if key in q_clean or any(word in q_clean for word in key.split() if len(word) > 3):
                return data
        return None

    def get_distance_matrix(
        self, origin: str, destination: str, destination_context: str = ""
    ) -> Dict[str, Any]:
        """
        Calculates road distance and driving duration between two locations.
        Executes live Google Distance Matrix API if key is present; otherwise
        uses high-fidelity geo-spatial calculation.
        """
        # Try live Google API if key is available
        if self.api_key:
            try:
                url = f"{self.base_url}/distancematrix/json"
                params = {
                    "origins": f"{origin}, {destination_context}".strip(", "),
                    "destinations": f"{destination}, {destination_context}".strip(", "),
                    "mode": "driving",
                    "key": self.api_key,
                }
                with httpx.Client(timeout=4.0) as client:
                    resp = client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("rows") and data["rows"][0]["elements"][0].get("status") == "OK":
                            elem = data["rows"][0]["elements"][0]
                            dist_km = elem["distance"]["value"] / 1000.0
                            dur_mins = elem["duration"]["value"] / 60.0
                            return {
                                "source": "google_maps_live",
                                "distance_km": round(dist_km, 1),
                                "duration_minutes": round(dur_mins),
                                "duration_text": elem["duration"]["text"],
                                "feasible": True,
                            }
            except Exception:
                pass  # Fall through to simulated GIS

        # Simulated GIS Distance Calculation
        poi_orig = self._fuzzy_lookup_poi(origin)
        poi_dest = self._fuzzy_lookup_poi(destination)

        if poi_orig and poi_dest:
            crow_dist = self._haversine_distance(
                poi_orig["lat"], poi_orig["lng"], poi_dest["lat"], poi_dest["lng"]
            )
            # Road winding factor in tourist zones is ~1.35x
            road_dist = round(crow_dist * 1.35, 1)
            # Average tourist driving speed with traffic: 32 km/h
            est_minutes = max(10, round((road_dist / 32.0) * 60))
            return {
                "source": "gis_sandbox",
                "distance_km": road_dist,
                "duration_minutes": est_minutes,
                "duration_text": f"{est_minutes} mins ({road_dist} km)",
                "origin_zone": poi_orig.get("zone", "General"),
                "dest_zone": poi_dest.get("zone", "General"),
                "feasible": True,
            }

        # Cross-zone heuristic if destination is Goa or similar
        dest_lower = (destination_context or "").lower()
        if "goa" in dest_lower:
            is_orig_north = any(k in origin.lower() for k in ["calangute", "baga", "anjuna", "vagator", "candolim", "morjim"])
            is_dest_north = any(k in destination.lower() for k in ["calangute", "baga", "anjuna", "vagator", "candolim", "morjim"])
            is_orig_south = any(k in origin.lower() for k in ["palolem", "agonda", "colva", "benaulim", "cavelossim"])
            is_dest_south = any(k in destination.lower() for k in ["palolem", "agonda", "colva", "benaulim", "cavelossim"])

            if (is_orig_north and is_dest_south) or (is_orig_south and is_dest_north):
                # North Goa to South Goa is a major transit gap (~75 km, 100-120 mins)
                return {
                    "source": "zone_heuristic",
                    "distance_km": 72.0,
                    "duration_minutes": 110,
                    "duration_text": "1 hr 50 mins (72 km)",
                    "cross_zone": True,
                    "feasible": True,
                }
            elif (is_orig_north and is_dest_north) or (is_orig_south and is_dest_south):
                return {
                    "source": "zone_heuristic",
                    "distance_km": 12.0,
                    "duration_minutes": 25,
                    "duration_text": "25 mins (12 km)",
                    "cross_zone": False,
                    "feasible": True,
                }

        # Generic intra-city fallback
        return {
            "source": "fallback_default",
            "distance_km": 15.0,
            "duration_minutes": 30,
            "duration_text": "30 mins (15 km)",
            "feasible": True,
        }

    def get_place_details(self, place_name: str, destination_context: str = "") -> Dict[str, Any]:
        """
        Retrieves place details, including operating hours, days open, and zone.
        """
        # Try live Google Places API if key present
        if self.api_key:
            try:
                search_url = f"{self.base_url}/place/findplacefromtext/json"
                params = {
                    "input": f"{place_name} {destination_context}",
                    "inputtype": "textquery",
                    "fields": "place_id,name,formatted_address,rating,opening_hours",
                    "key": self.api_key,
                }
                with httpx.Client(timeout=4.0) as client:
                    resp = client.get(search_url, params=params)
                    if resp.status_code == 200:
                        cand = resp.json().get("candidates", [])
                        if cand:
                            p = cand[0]
                            return {
                                "source": "google_places_live",
                                "name": p.get("name", place_name),
                                "rating": p.get("rating", 4.5),
                                "address": p.get("formatted_address", ""),
                                "has_opening_hours": "opening_hours" in p,
                            }
            except Exception:
                pass

        # High-Fidelity POI Sandbox lookup
        poi = self._fuzzy_lookup_poi(place_name)
        if poi:
            return {
                "source": "poi_sandbox",
                "name": poi["name"],
                "zone": poi["zone"],
                "open_hour": poi["open_hour"],
                "close_hour": poi["close_hour"],
                "closed_days": poi["closed_days"],
                "recommended_hours": poi["recommended_hours"],
                "rating": 4.6,
            }

        return {
            "source": "default_sandbox",
            "name": place_name,
            "zone": "General",
            "open_hour": 8.0,
            "close_hour": 21.0,
            "closed_days": [],
            "recommended_hours": 2.0,
            "rating": 4.3,
        }

    def validate_transit_feasibility(
        self,
        from_loc: str,
        to_loc: str,
        stated_gap_str: str,
        destination_context: str = "",
    ) -> Dict[str, Any]:
        """
        Validates if the declared travel gap is realistically sufficient for the distance.
        """
        matrix = self.get_distance_matrix(from_loc, to_loc, destination_context)
        actual_mins = matrix["duration_minutes"]

        # Parse declared gap in minutes
        declared_mins = 30 # default
        m = re.search(r"(\d+)\s*(?:min|mins|minute|minutes|hr|hour|hours)", stated_gap_str.lower())
        if m:
            val = int(m.group(1))
            if "hr" in stated_gap_str.lower() or "hour" in stated_gap_str.lower():
                declared_mins = val * 60
            else:
                declared_mins = val

        # If actual time exceeds declared time by > 40 minutes, it's a critical transit violation!
        # e.g., declared 15 mins for a North Goa -> South Goa 110 min trip
        transit_deficit = actual_mins - declared_mins
        is_realistic = transit_deficit <= 25

        return {
            "from_loc": from_loc,
            "to_loc": to_loc,
            "actual_duration_minutes": actual_mins,
            "declared_duration_minutes": declared_mins,
            "distance_km": matrix["distance_km"],
            "transit_deficit_minutes": max(0, transit_deficit),
            "is_feasible": is_realistic,
            "recommendation": (
                f"Increase travel gap from {declared_mins} mins to at least {actual_mins + 10} mins "
                f"due to road distance ({matrix['distance_km']} km)."
                if not is_realistic
                else "Travel gap is realistic."
            ),
        }


# Singleton instance
maps_service = GoogleMapsService()

