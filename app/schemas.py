"""Pydantic schemas for structured agent outputs.

Agents ask the LLM for JSON; we validate it into these models so downstream code and the UI
get predictable shapes. Validation failures are caught by the agent base and surfaced.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CompanyResearch(BaseModel):
    company: str = ""
    industry: str = ""
    focus: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    business_model: str = ""
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""


class RoleProfile(BaseModel):
    role: str = ""
    seniority: str = ""
    priorities: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    tech_adoption: str = ""


class Opportunity(BaseModel):
    outreach_angle: str = ""
    rationale: str = ""
    relevant_services: list[str] = Field(default_factory=list)


class Personalization(BaseModel):
    potential_interest: str = ""
    hook: str = ""
    talking_points: list[str] = Field(default_factory=list)
    summary: str = ""


class EmailContent(BaseModel):
    subject: str = ""
    body: str = ""


class WhatsAppContent(BaseModel):
    message: str = ""


class QAReview(BaseModel):
    quality_score: float = 0.0
    mentions_company: bool = False
    mentions_role: bool = False
    relevant: bool = False
    generic: bool = True
    grammar_ok: bool = False
    professional_tone: bool = False
    feedback: str = ""
