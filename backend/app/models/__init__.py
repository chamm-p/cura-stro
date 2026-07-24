"""ORM-Modelle. Hier importieren, damit Alembic-Autogenerate sie sieht."""

from app.models.asiair import AsiairRig  # noqa: F401
from app.models.calib import CalibFile, CalibMaster  # noqa: F401
from app.models.catalog import CatalogObject  # noqa: F401
from app.models.cloud_forecast import CloudForecast  # noqa: F401
from app.models.image import Image  # noqa: F401
from app.models.object_info import ObjectInfo  # noqa: F401
from app.models.observation import Observation  # noqa: F401
from app.models.observing import Camera, Filter, Location, Setup, Telescope  # noqa: F401
from app.models.result_file import ResultFile  # noqa: F401
from app.models.subframe import SubFrame  # noqa: F401
from app.models.solarsystem import SolarsystemObject  # noqa: F401
from app.models.user import AuthMethod, User, UserRole  # noqa: F401

__all__ = [
    "User",
    "CalibFile",
    "CalibMaster",
    "UserRole",
    "AuthMethod",
    "Location",
    "Telescope",
    "Camera",
    "Filter",
    "Setup",
    "CatalogObject",
    "Observation",
    "Image",
    "ObjectInfo",
    "AsiairRig",
    "SubFrame",
    "CloudForecast",
    "ResultFile",
]
