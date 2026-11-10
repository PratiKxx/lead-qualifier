"""Data contracts: what comes in on the webhook, and what the classifier must return.

The classifier output is constrained to Salesforce's *standard* Lead picklist values
(Industry, Rating) so a write can never fail on a bad picklist value.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class LeadPayload(BaseModel):
    """Inbound webhook body, e.g. from a website form, HubSpot, or Typeform."""

    event_id: str = Field(..., description="Unique id from the sender, used for idempotency")
    first_name: str | None = None
    last_name: str
    email: EmailStr
    company: str
    title: str | None = None
    website: str | None = None
    employee_count: int | None = Field(None, ge=0)
    country: str | None = None
    source: str = "Web"
    message: str | None = Field(None, description="Free text the lead typed into the form")


class SalesforceIndustry(str, Enum):
    """Standard Lead.Industry picklist values in a default Salesforce org."""

    AGRICULTURE = "Agriculture"
    APPAREL = "Apparel"
    BANKING = "Banking"
    BIOTECHNOLOGY = "Biotechnology"
    CHEMICALS = "Chemicals"
    COMMUNICATIONS = "Communications"
    CONSTRUCTION = "Construction"
    CONSULTING = "Consulting"
    EDUCATION = "Education"
    ELECTRONICS = "Electronics"
    ENERGY = "Energy"
    ENGINEERING = "Engineering"
    ENTERTAINMENT = "Entertainment"
    ENVIRONMENTAL = "Environmental"
    FINANCE = "Finance"
    FOOD_BEVERAGE = "Food & Beverage"
    GOVERNMENT = "Government"
    HEALTHCARE = "Healthcare"
    HOSPITALITY = "Hospitality"
    INSURANCE = "Insurance"
    MACHINERY = "Machinery"
    MANUFACTURING = "Manufacturing"
    MEDIA = "Media"
    NOT_FOR_PROFIT = "Not For Profit"
    RECREATION = "Recreation"
    RETAIL = "Retail"
    SHIPPING = "Shipping"
    TECHNOLOGY = "Technology"
    TELECOMMUNICATIONS = "Telecommunications"
    TRANSPORTATION = "Transportation"
    UTILITIES = "Utilities"
    OTHER = "Other"


class Rating(str, Enum):
    """Standard Lead.Rating picklist values."""

    HOT = "Hot"
    WARM = "Warm"
    COLD = "Cold"


class LeadClassification(BaseModel):
    """What the LLM must return. Validated by the SDK against this schema."""

    industry: SalesforceIndustry
    fit_score: int = Field(..., ge=0, le=100, description="0-100 match against the ICP")
    rating: Rating
    reasons: list[str] = Field(..., description="2-4 short, evidence-based reasons for the score")
    next_action: str = Field(..., description="One sentence: what sales should do next")
    needs_human_review: bool = Field(
        ..., description="True when the payload is too thin or contradictory to score confidently"
    )


class ClassifiedLead(BaseModel):
    lead: LeadPayload
    classification: LeadClassification
    classifier: str  # "claude" or "rules", recorded for auditability
