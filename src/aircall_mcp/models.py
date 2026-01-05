"""Pydantic models for MCP tool input validation."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ResponseFormat(str, Enum):
    """Output format for tool responses."""
    MARKDOWN = "markdown"
    JSON = "json"


class CallDirection(str, Enum):
    """Call direction filter."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class TranscriptFormat(str, Enum):
    """Transcript output format."""
    TEXT = "text"  # Readable conversation format
    STRUCTURED = "structured"  # With timestamps
    RAW = "raw"  # API response as-is


class SpeakerLabels(str, Enum):
    """How to label speakers in transcripts."""
    ROLE = "role"  # Agent/Customer/AI Assistant
    TYPE = "type"  # internal/external/ai_voice_agent
    DETAILED = "detailed"  # Includes IDs


def _validate_date(v: Optional[str]) -> Optional[str]:
    """Validate date format (ISO or Unix timestamp)."""
    if v is None:
        return v
    # Accept Unix timestamp
    if v.isdigit():
        return v
    # Validate ISO format
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v
    except ValueError:
        raise ValueError(f"Invalid date format: {v}. Use ISO format (2024-01-15) or Unix timestamp.")


class ListCallsInput(BaseModel):
    """Input for listing calls with filtering and pagination."""

    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum results to return (1-100)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of results to skip for pagination",
    )
    direction: Optional[CallDirection] = Field(
        default=None,
        description="Filter by call direction: 'inbound' or 'outbound'",
    )
    from_date: Optional[str] = Field(
        default=None,
        description="Start date (ISO format: 2024-01-15 or Unix timestamp)",
    )
    to_date: Optional[str] = Field(
        default=None,
        description="End date (ISO format: 2024-01-15 or Unix timestamp)",
    )
    min_duration: Optional[int] = Field(
        default=None,
        ge=0,
        description="Minimum call duration in seconds",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        max_length=10,
        description="Filter by tag names",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )

    @field_validator("from_date", "to_date")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        return _validate_date(v)


class GetCallInput(BaseModel):
    """Input for getting a specific call."""

    call_id: int = Field(
        ...,
        description="The Aircall call ID",
        gt=0,
    )
    include_transcript: bool = Field(
        default=False,
        description="Include the call transcript in the response",
    )
    include_summary: bool = Field(
        default=False,
        description="Include the AI summary in the response",
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class GetTranscriptInput(BaseModel):
    """Input for getting a call transcript."""

    call_id: int = Field(
        ...,
        description="The Aircall call ID",
        gt=0,
    )
    format: TranscriptFormat = Field(
        default=TranscriptFormat.TEXT,
        description="Transcript format: 'text' (readable), 'structured' (with timestamps), or 'raw'",
    )
    speaker_labels: SpeakerLabels = Field(
        default=SpeakerLabels.ROLE,
        description="Speaker labels: 'role' (Agent/Customer), 'type' (internal/external), or 'detailed'",
    )


class SearchTranscriptsInput(BaseModel):
    """Input for searching across transcripts."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=200,
        description="Text to search for in transcripts",
    )
    call_ids: Optional[list[int]] = Field(
        default=None,
        max_length=20,
        description="Limit search to specific call IDs (max 20)",
    )
    from_date: Optional[str] = Field(
        default=None,
        description="Start date for call range",
    )
    to_date: Optional[str] = Field(
        default=None,
        description="End date for call range",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum calls to search (1-50)",
    )
    case_sensitive: bool = Field(
        default=False,
        description="Case-sensitive search",
    )

    @field_validator("from_date", "to_date")
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        return _validate_date(v)


class GetSummaryInput(BaseModel):
    """Input for getting a call summary."""

    call_id: int = Field(
        ...,
        description="The Aircall call ID",
        gt=0,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )


class GetCallInsightsInput(BaseModel):
    """Input for getting combined call insights."""

    call_id: int = Field(
        ...,
        description="The Aircall call ID",
        gt=0,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Output format: 'markdown' or 'json'",
    )
