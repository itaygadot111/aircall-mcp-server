"""MCP tools for Aircall API access."""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP


def parse_natural_date(text: str) -> tuple[datetime | None, datetime | None]:
    """Parse natural language date references into (from_date, to_date) tuple.

    Supports:
    - "today", "yesterday"
    - "this week", "last week"
    - "this month", "last month"
    - "past N days/hours"
    - ISO dates like "2024-01-15"

    Returns start of day for from_date and end of day for to_date.
    """
    text = text.lower().strip()
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    if text in ("today", "today's"):
        return today_start, today_end

    if text == "yesterday":
        yesterday = today_start - timedelta(days=1)
        return yesterday, yesterday.replace(hour=23, minute=59, second=59)

    if text in ("this week", "this week's"):
        week_start = today_start - timedelta(days=today_start.weekday())
        return week_start, today_end

    if text in ("last week", "last week's"):
        this_week_start = today_start - timedelta(days=today_start.weekday())
        last_week_start = this_week_start - timedelta(days=7)
        last_week_end = this_week_start - timedelta(seconds=1)
        return last_week_start, last_week_end

    if text in ("this month", "this month's"):
        month_start = today_start.replace(day=1)
        return month_start, today_end

    if text in ("last month", "last month's"):
        this_month_start = today_start.replace(day=1)
        last_month_end = this_month_start - timedelta(seconds=1)
        last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0)
        return last_month_start, last_month_end

    # "past N days" or "last N days"
    match = re.match(r"(?:past|last)\s+(\d+)\s+days?", text)
    if match:
        days = int(match.group(1))
        return today_start - timedelta(days=days), today_end

    # "past N hours" or "last N hours"
    match = re.match(r"(?:past|last)\s+(\d+)\s+hours?", text)
    if match:
        hours = int(match.group(1))
        return now - timedelta(hours=hours), now

    # Try ISO date
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed, parsed.replace(hour=23, minute=59, second=59)
    except ValueError:
        pass

    return None, None


def extract_date_from_query(query: str) -> tuple[str, datetime | None, datetime | None]:
    """Extract date references from a natural language query.

    Returns (cleaned_query, from_date, to_date).
    """
    query_lower = query.lower()

    # Date patterns to look for (ordered by specificity)
    date_patterns = [
        (r"\btoday'?s?\b", "today"),
        (r"\byesterday'?s?\b", "yesterday"),
        (r"\bthis week'?s?\b", "this week"),
        (r"\blast week'?s?\b", "last week"),
        (r"\bthis month'?s?\b", "this month"),
        (r"\blast month'?s?\b", "last month"),
        (r"\b(?:past|last)\s+\d+\s+days?\b", None),  # Keep the match
        (r"\b(?:past|last)\s+\d+\s+hours?\b", None),  # Keep the match
    ]

    from_date, to_date = None, None
    cleaned_query = query

    for pattern, replacement in date_patterns:
        match = re.search(pattern, query_lower)
        if match:
            matched_text = match.group(0)
            from_date, to_date = parse_natural_date(replacement or matched_text)
            if from_date:
                # Remove the date reference from the query
                cleaned_query = re.sub(pattern, "", query, flags=re.IGNORECASE).strip()
                # Clean up extra spaces and common connectors
                cleaned_query = re.sub(r"\s+(from|on|in|during)\s*$", "", cleaned_query, flags=re.IGNORECASE)
                cleaned_query = re.sub(r"^\s*(from|on|in|during)\s+", "", cleaned_query, flags=re.IGNORECASE)
                cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()
                break

    return cleaned_query, from_date, to_date

from .client import AircallClient, AircallAPIError
from .models import (
    ListCallsInput,
    GetCallInput,
    GetTranscriptInput,
    SearchTranscriptsInput,
    GetSummaryInput,
    GetCallInsightsInput,
    ResponseFormat,
    TranscriptFormat,
    SpeakerLabels,
)


def format_datetime(timestamp: int | None) -> str:
    """Format Unix timestamp to readable datetime."""
    if not timestamp:
        return "Unknown"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: int | None) -> str:
    """Format duration in seconds to readable string."""
    if not seconds:
        return "0s"
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_transcript_text(
    transcript: dict[str, Any],
    speaker_labels: SpeakerLabels,
    include_timestamps: bool = False,
) -> str:
    """Format transcript utterances into readable text."""
    content = transcript.get("content", {})
    utterances = content.get("utterances", [])

    if not utterances:
        return "No transcript content available."

    lines = []
    for u in utterances:
        participant_type = u.get("participant_type", "unknown")
        text = u.get("text", "").strip()

        if not text:
            continue

        # Determine speaker label
        if speaker_labels == SpeakerLabels.ROLE:
            if participant_type == "internal":
                speaker = "Agent"
            elif participant_type == "ai_voice_agent":
                speaker = "AI Assistant"
            elif participant_type == "external":
                speaker = "Customer"
            else:
                speaker = "Unknown"
        elif speaker_labels == SpeakerLabels.TYPE:
            speaker = participant_type
        else:  # DETAILED
            speaker = participant_type
            if u.get("ai_voice_agent_id"):
                speaker += f" ({u['ai_voice_agent_id'][:8]}...)"
            elif u.get("phone_number"):
                speaker += f" ({u['phone_number']})"

        if include_timestamps:
            start = u.get("start_time", 0)
            lines.append(f"[{start:.1f}s] {speaker}: {text}")
        else:
            lines.append(f"{speaker}: {text}")

    return "\n".join(lines)


def register_tools(mcp: FastMCP, client: AircallClient):
    """Register all Aircall tools with the MCP server."""

    @mcp.tool()
    async def aircall_list_calls(
        limit: int = 20,
        offset: int = 0,
        direction: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        min_duration: int | None = None,
        tags: list[str] | None = None,
        response_format: str = "markdown",
    ) -> str:
        """List calls from Aircall with filtering and pagination.

        Args:
            limit: Maximum results to return (1-100, default: 20)
            offset: Number of results to skip for pagination (default: 0)
            direction: Filter by call direction - 'inbound' or 'outbound'
            from_date: Start date (ISO format: 2024-01-15 or Unix timestamp)
            to_date: End date (ISO format: 2024-01-15 or Unix timestamp)
            min_duration: Minimum call duration in seconds
            tags: Filter by tag names
            response_format: Output format - 'markdown' or 'json' (default: markdown)

        Returns:
            List of calls with metadata (id, duration, direction, date, agent, tags)
        """
        try:
            params = ListCallsInput(
                limit=limit,
                offset=offset,
                direction=direction,
                from_date=from_date,
                to_date=to_date,
                min_duration=min_duration,
                tags=tags,
                response_format=response_format,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            # Convert dates to timestamps if needed
            from_ts = None
            to_ts = None
            if params.from_date:
                if params.from_date.isdigit():
                    from_ts = int(params.from_date)
                else:
                    from_ts = int(datetime.fromisoformat(params.from_date.replace("Z", "+00:00")).timestamp())
            if params.to_date:
                if params.to_date.isdigit():
                    to_ts = int(params.to_date)
                else:
                    to_ts = int(datetime.fromisoformat(params.to_date.replace("Z", "+00:00")).timestamp())

            # Fetch calls
            page = (params.offset // params.limit) + 1
            data = await client.list_calls(
                page=page,
                per_page=params.limit,
                direction=params.direction.value if params.direction else None,
                from_timestamp=from_ts,
                to_timestamp=to_ts,
            )

            calls = data.get("calls", [])

            # Apply client-side filters
            if params.min_duration:
                calls = [c for c in calls if c.get("duration", 0) >= params.min_duration]
            if params.tags:
                tag_set = set(t.lower() for t in params.tags)
                calls = [
                    c for c in calls
                    if any(t.get("name", "").lower() in tag_set for t in c.get("tags", []))
                ]

            if not calls:
                return "No calls found matching the specified criteria."

            # Build response
            meta = data.get("meta", {})
            total = meta.get("total", len(calls))
            has_more = params.offset + len(calls) < total

            if params.response_format == "markdown":
                lines = ["# Aircall Calls", ""]
                lines.append(f"Showing {len(calls)} calls (offset: {params.offset})")
                if has_more:
                    lines.append(f"*Use offset={params.offset + params.limit} for next page*")
                lines.append("")

                for call in calls:
                    user = call.get("user") or {}
                    number = call.get("number") or {}
                    duration = call.get("duration", 0)
                    started = format_datetime(call.get("started_at"))

                    lines.append(f"## Call {call['id']}")
                    lines.append(f"- **Direction**: {call.get('direction', 'unknown')}")
                    lines.append(f"- **Duration**: {format_duration(duration)}")
                    lines.append(f"- **Date**: {started}")
                    if user.get("name"):
                        lines.append(f"- **Agent**: {user['name']}")
                    if number.get("name"):
                        lines.append(f"- **Number**: {number['name']}")
                    call_tags = [t.get("name") for t in call.get("tags", [])]
                    if call_tags:
                        lines.append(f"- **Tags**: {', '.join(call_tags)}")
                    lines.append("")

                return "\n".join(lines)
            else:
                response = {
                    "total": total,
                    "count": len(calls),
                    "offset": params.offset,
                    "has_more": has_more,
                    "calls": [
                        {
                            "id": c["id"],
                            "direction": c.get("direction"),
                            "duration_seconds": c.get("duration"),
                            "started_at": c.get("started_at"),
                            "date": format_datetime(c.get("started_at")),
                            "agent_name": (c.get("user") or {}).get("name"),
                            "number_name": (c.get("number") or {}).get("name"),
                            "tags": [t.get("name") for t in c.get("tags", [])],
                        }
                        for c in calls
                    ],
                }
                return json.dumps(response, indent=2)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_get_call(
        call_id: int,
        include_transcript: bool = False,
        include_summary: bool = False,
        response_format: str = "markdown",
    ) -> str:
        """Get detailed information about a specific call.

        Args:
            call_id: The Aircall call ID
            include_transcript: Include the call transcript (default: false)
            include_summary: Include the AI summary (default: false)
            response_format: Output format - 'markdown' or 'json' (default: markdown)

        Returns:
            Call details including metadata, and optionally transcript and summary
        """
        try:
            params = GetCallInput(
                call_id=call_id,
                include_transcript=include_transcript,
                include_summary=include_summary,
                response_format=response_format,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            call = await client.get_call(params.call_id)

            transcript = None
            summary = None

            if params.include_transcript:
                transcript = await client.get_transcript(params.call_id)
            if params.include_summary:
                summary = await client.get_summary(params.call_id)

            if params.response_format == "markdown":
                user = call.get("user") or {}
                number = call.get("number") or {}
                duration = call.get("duration", 0)

                lines = [f"# Call {call['id']}", ""]
                lines.append(f"- **Direction**: {call.get('direction', 'unknown')}")
                lines.append(f"- **Duration**: {format_duration(duration)}")
                lines.append(f"- **Date**: {format_datetime(call.get('started_at'))}")
                if user.get("name"):
                    lines.append(f"- **Agent**: {user['name']}")
                if number.get("name"):
                    lines.append(f"- **Number**: {number['name']}")
                call_tags = [t.get("name") for t in call.get("tags", [])]
                if call_tags:
                    lines.append(f"- **Tags**: {', '.join(call_tags)}")

                if summary:
                    lines.append("")
                    lines.append("## Summary")
                    lines.append(summary.get("content", "No summary content."))

                if transcript:
                    lines.append("")
                    lines.append("## Transcript")
                    lines.append(format_transcript_text(transcript, SpeakerLabels.ROLE))

                return "\n".join(lines)
            else:
                response = {
                    "id": call["id"],
                    "direction": call.get("direction"),
                    "duration_seconds": call.get("duration"),
                    "started_at": call.get("started_at"),
                    "date": format_datetime(call.get("started_at")),
                    "agent_name": (call.get("user") or {}).get("name"),
                    "number_name": (call.get("number") or {}).get("name"),
                    "tags": [t.get("name") for t in call.get("tags", [])],
                }
                if summary:
                    response["summary"] = summary.get("content")
                if transcript:
                    response["transcript"] = format_transcript_text(transcript, SpeakerLabels.ROLE)
                return json.dumps(response, indent=2)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_get_transcript(
        call_id: int,
        format: str = "text",
        speaker_labels: str = "role",
    ) -> str:
        """Get the transcript for a specific call.

        Args:
            call_id: The Aircall call ID
            format: Transcript format - 'text' (readable), 'structured' (with timestamps), or 'raw' (API response)
            speaker_labels: How to label speakers - 'role' (Agent/Customer), 'type' (internal/external), or 'detailed'

        Returns:
            The formatted call transcript
        """
        try:
            params = GetTranscriptInput(
                call_id=call_id,
                format=format,
                speaker_labels=speaker_labels,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            transcript = await client.get_transcript(params.call_id)

            if not transcript:
                return f"No transcript available for call {params.call_id}. The call may not have been recorded or transcribed."

            if params.format == "raw":
                return json.dumps(transcript, indent=2)

            include_timestamps = params.format == "structured"
            return format_transcript_text(transcript, params.speaker_labels, include_timestamps)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_search_transcripts(
        query: str,
        call_ids: list[int] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 10,
        case_sensitive: bool = False,
    ) -> str:
        """Search across call transcripts for specific content.

        Args:
            query: Text to search for in transcripts (min 2 characters)
            call_ids: Limit search to specific call IDs (max 20)
            from_date: Start date for call range (ISO format or Unix timestamp)
            to_date: End date for call range (ISO format or Unix timestamp)
            limit: Maximum calls to search (1-50, default: 10)
            case_sensitive: Case-sensitive search (default: false)

        Returns:
            List of matching calls with relevant transcript excerpts
        """
        try:
            params = SearchTranscriptsInput(
                query=query,
                call_ids=call_ids,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                case_sensitive=case_sensitive,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            # Get calls to search
            if params.call_ids:
                # Fetch specific calls
                calls_to_search = []
                for cid in params.call_ids[:params.limit]:
                    try:
                        call = await client.get_call(cid)
                        calls_to_search.append(call)
                    except AircallAPIError:
                        pass  # Skip calls that don't exist
            else:
                # Convert dates to timestamps
                from_ts = None
                to_ts = None
                if params.from_date:
                    if params.from_date.isdigit():
                        from_ts = int(params.from_date)
                    else:
                        from_ts = int(datetime.fromisoformat(params.from_date.replace("Z", "+00:00")).timestamp())
                if params.to_date:
                    if params.to_date.isdigit():
                        to_ts = int(params.to_date)
                    else:
                        to_ts = int(datetime.fromisoformat(params.to_date.replace("Z", "+00:00")).timestamp())

                data = await client.list_calls(
                    per_page=params.limit,
                    from_timestamp=from_ts,
                    to_timestamp=to_ts,
                )
                calls_to_search = data.get("calls", [])

            if not calls_to_search:
                return "No calls found to search."

            # Search transcripts
            search_query = params.query if params.case_sensitive else params.query.lower()
            matches = []

            for call in calls_to_search:
                call_id = call.get("id")
                transcript = await client.get_transcript(call_id)

                if not transcript:
                    continue

                content = transcript.get("content", {})
                utterances = content.get("utterances", [])

                matching_excerpts = []
                for u in utterances:
                    text = u.get("text", "")
                    search_text = text if params.case_sensitive else text.lower()

                    if search_query in search_text:
                        participant = u.get("participant_type", "unknown")
                        if participant == "internal":
                            speaker = "Agent"
                        elif participant == "ai_voice_agent":
                            speaker = "AI Assistant"
                        elif participant == "external":
                            speaker = "Customer"
                        else:
                            speaker = "Unknown"
                        matching_excerpts.append(f"{speaker}: {text}")

                if matching_excerpts:
                    matches.append({
                        "call_id": call_id,
                        "date": format_datetime(call.get("started_at")),
                        "direction": call.get("direction"),
                        "excerpts": matching_excerpts[:5],  # Limit excerpts per call
                    })

            if not matches:
                return f"No transcripts found containing '{params.query}'."

            # Format response
            lines = [f"# Search Results for '{params.query}'", ""]
            lines.append(f"Found {len(matches)} calls with matching content")
            lines.append("")

            for match in matches:
                lines.append(f"## Call {match['call_id']}")
                lines.append(f"- **Date**: {match['date']}")
                lines.append(f"- **Direction**: {match['direction']}")
                lines.append("")
                lines.append("**Matching excerpts:**")
                for excerpt in match["excerpts"]:
                    lines.append(f"> {excerpt}")
                lines.append("")

            return "\n".join(lines)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_get_summary(
        call_id: int,
        response_format: str = "markdown",
    ) -> str:
        """Get the AI-generated summary for a specific call.

        Args:
            call_id: The Aircall call ID
            response_format: Output format - 'markdown' or 'json' (default: markdown)

        Returns:
            The AI-generated call summary
        """
        try:
            params = GetSummaryInput(
                call_id=call_id,
                response_format=response_format,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            summary = await client.get_summary(params.call_id)

            if not summary:
                return f"No summary available for call {params.call_id}. The summary may still be processing or unavailable."

            if params.response_format == "markdown":
                lines = [f"# Summary for Call {params.call_id}", ""]
                lines.append(summary.get("content", "No summary content."))
                return "\n".join(lines)
            else:
                return json.dumps({
                    "call_id": params.call_id,
                    "summary": summary.get("content"),
                }, indent=2)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_get_call_insights(
        call_id: int,
        response_format: str = "markdown",
    ) -> str:
        """Get combined insights for a call including metadata, transcript, and summary.

        This is useful for getting a complete picture of a call in a single request.

        Args:
            call_id: The Aircall call ID
            response_format: Output format - 'markdown' or 'json' (default: markdown)

        Returns:
            Complete call context including metadata, transcript, and summary
        """
        try:
            params = GetCallInsightsInput(
                call_id=call_id,
                response_format=response_format,
            )
        except Exception as e:
            return f"Error: Invalid parameters - {e}"

        try:
            # Fetch all data
            call = await client.get_call(params.call_id)
            transcript = await client.get_transcript(params.call_id)
            summary = await client.get_summary(params.call_id)

            user = call.get("user") or {}
            number = call.get("number") or {}

            if params.response_format == "markdown":
                lines = [f"# Call Insights: {params.call_id}", ""]

                # Metadata section
                lines.append("## Call Details")
                lines.append(f"- **Direction**: {call.get('direction', 'unknown')}")
                lines.append(f"- **Duration**: {format_duration(call.get('duration'))}")
                lines.append(f"- **Date**: {format_datetime(call.get('started_at'))}")
                if user.get("name"):
                    lines.append(f"- **Agent**: {user['name']}")
                if number.get("name"):
                    lines.append(f"- **Number**: {number['name']}")
                call_tags = [t.get("name") for t in call.get("tags", [])]
                if call_tags:
                    lines.append(f"- **Tags**: {', '.join(call_tags)}")

                # Summary section
                lines.append("")
                lines.append("## Summary")
                if summary:
                    lines.append(summary.get("content", "No summary content."))
                else:
                    lines.append("*No summary available*")

                # Transcript section
                lines.append("")
                lines.append("## Transcript")
                if transcript:
                    lines.append(format_transcript_text(transcript, SpeakerLabels.ROLE))
                else:
                    lines.append("*No transcript available*")

                return "\n".join(lines)
            else:
                response = {
                    "call_id": params.call_id,
                    "direction": call.get("direction"),
                    "duration_seconds": call.get("duration"),
                    "started_at": call.get("started_at"),
                    "date": format_datetime(call.get("started_at")),
                    "agent_name": user.get("name"),
                    "number_name": number.get("name"),
                    "tags": [t.get("name") for t in call.get("tags", [])],
                    "summary": summary.get("content") if summary else None,
                    "transcript": format_transcript_text(transcript, SpeakerLabels.ROLE) if transcript else None,
                }
                return json.dumps(response, indent=2)

        except AircallAPIError as e:
            return f"Error: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"

    @mcp.tool()
    async def aircall_ask(
        question: str,
        limit: int = 20,
    ) -> str:
        """Ask a natural language question about your Aircall data.

        This is the recommended tool for answering questions about calls. It handles:
        - Natural language date parsing ("today", "yesterday", "last week", etc.)
        - Searching transcripts for specific topics or keywords
        - Finding calls with specific characteristics
        - Parallel processing for faster results

        Examples:
        - "Were there any calls about AI Assist Pro today?"
        - "Show me calls from yesterday mentioning pricing"
        - "Find calls this week where customers complained"
        - "What calls happened in the last 3 days about refunds?"

        Args:
            question: Your question in natural language
            limit: Maximum calls to analyze (1-50, default: 20)

        Returns:
            A clear answer to your question with relevant call details
        """
        if not question or len(question.strip()) < 3:
            return "Please provide a question with at least 3 characters."

        limit = max(1, min(50, limit))

        try:
            # Extract date references from the question
            cleaned_query, from_date, to_date = extract_date_from_query(question)

            # Convert dates to timestamps for API
            from_ts = int(from_date.timestamp()) if from_date else None
            to_ts = int(to_date.timestamp()) if to_date else None

            # Extract potential search terms (remove common question words)
            search_terms = cleaned_query
            for remove in ["were there", "was there", "are there", "is there",
                           "any calls", "calls", "call", "about", "regarding",
                           "mentioning", "where", "what", "which", "how many",
                           "show me", "find", "get", "list", "search for"]:
                search_terms = re.sub(rf"\b{remove}\b", "", search_terms, flags=re.IGNORECASE)
            search_terms = re.sub(r"\s+", " ", search_terms).strip()
            search_terms = search_terms.strip("?.,!")

            # Build date range description
            date_desc = ""
            if from_date and to_date:
                if from_date.date() == to_date.date():
                    date_desc = f"on {from_date.strftime('%Y-%m-%d')}"
                else:
                    date_desc = f"from {from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}"
            elif from_date:
                date_desc = f"since {from_date.strftime('%Y-%m-%d')}"

            # First, get calls in the date range
            data = await client.list_calls(
                per_page=limit,
                from_timestamp=from_ts,
                to_timestamp=to_ts,
            )
            calls = data.get("calls", [])

            if not calls:
                no_calls_msg = f"No calls found {date_desc}." if date_desc else "No calls found."
                return no_calls_msg

            # If we have search terms, search through transcripts in parallel
            if search_terms and len(search_terms) >= 2:
                async def search_call_transcript(call: dict) -> dict | None:
                    """Search a single call's transcript for matches."""
                    call_id = call.get("id")
                    try:
                        transcript = await client.get_transcript(call_id)
                        if not transcript:
                            return None

                        content = transcript.get("content", {})
                        utterances = content.get("utterances", [])

                        search_lower = search_terms.lower()
                        matching_excerpts = []

                        for u in utterances:
                            text = u.get("text", "")
                            if search_lower in text.lower():
                                participant = u.get("participant_type", "unknown")
                                if participant == "internal":
                                    speaker = "Agent"
                                elif participant == "ai_voice_agent":
                                    speaker = "AI Assistant"
                                elif participant == "external":
                                    speaker = "Customer"
                                else:
                                    speaker = "Unknown"
                                matching_excerpts.append(f"{speaker}: {text}")

                        if matching_excerpts:
                            return {
                                "call": call,
                                "excerpts": matching_excerpts[:3],  # Limit to 3 excerpts
                            }
                    except Exception:
                        pass  # Skip calls with errors
                    return None

                # Search transcripts in parallel with timeout
                try:
                    tasks = [search_call_transcript(call) for call in calls]
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=60.0  # 60 second timeout for all searches
                    )
                    matches = [r for r in results if r and not isinstance(r, Exception)]
                except asyncio.TimeoutError:
                    return f"Search timed out after 60 seconds. Try narrowing your date range or being more specific."

                # Format results
                if not matches:
                    searched_msg = f"Searched {len(calls)} calls {date_desc}" if date_desc else f"Searched {len(calls)} calls"
                    return f"No calls found mentioning '{search_terms}'. {searched_msg}, but none contained matching content in their transcripts."

                lines = [f"# Found {len(matches)} call(s) mentioning '{search_terms}'"]
                if date_desc:
                    lines.append(f"*{date_desc}*")
                lines.append("")

                for match in matches:
                    call = match["call"]
                    user = call.get("user") or {}
                    lines.append(f"## Call {call['id']}")
                    lines.append(f"- **Date**: {format_datetime(call.get('started_at'))}")
                    lines.append(f"- **Direction**: {call.get('direction', 'unknown')}")
                    lines.append(f"- **Duration**: {format_duration(call.get('duration'))}")
                    if user.get("name"):
                        lines.append(f"- **Agent**: {user['name']}")
                    lines.append("")
                    lines.append("**Relevant excerpts:**")
                    for excerpt in match["excerpts"]:
                        lines.append(f"> {excerpt}")
                    lines.append("")

                return "\n".join(lines)

            else:
                # No search terms - just list the calls
                lines = [f"# {len(calls)} call(s) found"]
                if date_desc:
                    lines.append(f"*{date_desc}*")
                lines.append("")

                for call in calls[:10]:  # Limit to 10 for overview
                    user = call.get("user") or {}
                    lines.append(f"## Call {call['id']}")
                    lines.append(f"- **Date**: {format_datetime(call.get('started_at'))}")
                    lines.append(f"- **Direction**: {call.get('direction', 'unknown')}")
                    lines.append(f"- **Duration**: {format_duration(call.get('duration'))}")
                    if user.get("name"):
                        lines.append(f"- **Agent**: {user['name']}")
                    lines.append("")

                if len(calls) > 10:
                    lines.append(f"*...and {len(calls) - 10} more calls*")
                    lines.append("")
                    lines.append("Tip: Add a search term to find specific content (e.g., 'calls about pricing today')")

                return "\n".join(lines)

        except AircallAPIError as e:
            return f"Error accessing Aircall: {e.message}"
        except Exception as e:
            return f"Error: {str(e)}"
