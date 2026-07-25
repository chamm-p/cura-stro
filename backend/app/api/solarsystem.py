"""Solarsystem-API: Planetendaten und 3D-Positionen."""

from datetime import date
from fastapi import APIRouter

router = APIRouter()

# Epoche: 2000-01-01 (J2000)
EPOCH = date(2000, 1, 1)

BODIES = [
    {
        "name": "Sonne",
        "radius": 696340,
        "color": "#FDB813",
        "orbitRadius": 0,
        "orbitalPeriod": 365.25,
        "rotationPeriod": 25.05,
        "info": {
            "mass": "1.989 × 10³⁰ kg",
            "diameter": "1.392.700 km",
            "temperature": "5.500 °C (Oberfläche)",
            "description": "Unser Stern, ein gelber Zwerg vom Typ G2V. Sie enthält 99,86 % der gesamten Masse des Sonnensystems.",
        },
    },
    {
        "name": "Merkur",
        "radius": 2439.7,
        "color": "#A0522D",
        "orbitRadius": 57.9,
        "orbitalPeriod": 87.97,
        "rotationPeriod": 58.65,
        "info": {
            "mass": "3.301 × 10²³ kg",
            "diameter": "4.879 km",
            "temperature": "-173 bis 427 °C",
            "description": "Der kleinste und sonnennächste Planet. Ohne nennenswerte Atmosphäre extrem Temperaturschwankungen.",
        },
    },
    {
        "name": "Venus",
        "radius": 6051.8,
        "color": "#DEB887",
        "orbitRadius": 108.2,
        "orbitalPeriod": 224.7,
        "rotationPeriod": -243.02,
        "info": {
            "mass": "4.867 × 10²⁴ kg",
            "diameter": "12.104 km",
            "temperature": "462 °C (Durchschnitt)",
            "description": "Der heiße Zwilling der Erde mit dichter CO₂-Atmosphäre. Dreht sich rückwärts (retrograd).",
        },
    },
    {
        "name": "Erde",
        "radius": 6371.0,
        "color": "#4FC3F7",
        "orbitRadius": 149.6,
        "orbitalPeriod": 365.25,
        "rotationPeriod": 0.997,
        "info": {
            "mass": "5.972 × 10²⁴ kg",
            "diameter": "12.742 km",
            "temperature": "15 °C (Durchschnitt)",
            "description": "Unser Heimatplanet, der einzige bekannte mit flüssigem Wasser und Leben.",
        },
    },
    {
        "name": "Mars",
        "radius": 3389.5,
        "color": "#E5534B",
        "orbitRadius": 227.9,
        "orbitalPeriod": 687.0,
        "rotationPeriod": 1.026,
        "info": {
            "mass": "6.417 × 10²³ kg",
            "diameter": "6.779 km",
            "temperature": "-63 °C (Durchschnitt)",
            "description": "Der rote Planet mit dem höchsten Vulkan (Olympus Mons) und polaren Eiskappen.",
        },
    },
    {
        "name": "Jupiter",
        "radius": 69911,
        "color": "#DAA520",
        "orbitRadius": 778.5,
        "orbitalPeriod": 4332.59,
        "rotationPeriod": 0.414,
        "info": {
            "mass": "1.898 × 10²⁷ kg",
            "diameter": "139.822 km",
            "temperature": "-108 °C (Wolkenobergrenze)",
            "description": "Der Gasriese mit dem Großen Roten Fleck, einem Jahrhundertsturm. Hat über 90 Monde.",
        },
    },
    {
        "name": "Saturn",
        "radius": 58232,
        "color": "#F4D03F",
        "orbitRadius": 1433.5,
        "orbitalPeriod": 10759.22,
        "rotationPeriod": 0.444,
        "info": {
            "mass": "5.683 × 10²⁶ kg",
            "diameter": "116.464 km",
            "temperature": "-139 °C (Wolkenobergrenze)",
            "description": "Berühmt für sein spektakuläres Ringsystem aus Eis und Gestein.",
        },
    },
    {
        "name": "Uranus",
        "radius": 25362,
        "color": "#7EC8E3",
        "orbitRadius": 2872.5,
        "orbitalPeriod": 30688.5,
        "rotationPeriod": -0.718,
        "info": {
            "mass": "8.681 × 10²⁵ kg",
            "diameter": "50.724 km",
            "temperature": "-197 °C (Wolkenobergrenze)",
            "description": "Der Eisriese, der fast auf der Seite rollt (Rotationsachse ~98° geneigt).",
        },
    },
    {
        "name": "Neptun",
        "radius": 24622,
        "color": "#4169E1",
        "orbitRadius": 4495.1,
        "orbitalPeriod": 60182.0,
        "rotationPeriod": 0.671,
        "info": {
            "mass": "1.024 × 10²⁶ kg",
            "diameter": "49.244 km",
            "temperature": "-201 °C (Wolkenobergrenze)",
            "description": "Der sonnfernste Planet mit den stärksten Winden (bis 2.100 km/h) im Sonnensystem.",
        },
    },
]


@router.get("/bodies")
def get_bodies():
    """Liste aller Himmelskörper (Sonne + 8 Planeten)."""
    return BODIES


def _days_since_epoch(d: date) -> float:
    """Tage seit J2000-Epoche."""
    return (d - EPOCH).days


@router.get("/positions")
def get_positions(date_str: str = "2025-01-01"):
    """Berechnete 3D-Positionen aller Körper für ein Datum.
    
    Einfache Kreisbahn-Mechanik:
      winkel = 2π × (Tage seit Epoche / orbitalPeriod)
      x = orbitRadius × cos(winkel)
      z = orbitRadius × sin(winkel)
      y = 0
    """
    d = date.fromisoformat(date_str)
    days = _days_since_epoch(d)

    positions = []
    for body in BODIES:
        if body["orbitRadius"] == 0:
            # Sonne im Zentrum
            positions.append({
                "name": body["name"],
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
            })
        else:
            omega = 2 * 3.141592653589793 * (days / body["orbitalPeriod"])
            positions.append({
                "name": body["name"],
                "x": round(body["orbitRadius"] * __import__("math").cos(omega), 4),
                "y": 0.0,
                "z": round(body["orbitRadius"] * __import__("math").sin(omega), 4),
            })

    return positions