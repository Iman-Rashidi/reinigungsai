"""Persistent multi-source opportunity discovery for ReinigungsRadar NRW."""

from .models import Opportunity
from .service import run_discovery
from .store import OpportunityStore

__all__ = ["Opportunity", "OpportunityStore", "run_discovery"]
