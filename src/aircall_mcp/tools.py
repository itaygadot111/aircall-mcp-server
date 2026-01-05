"""MCP tools for Aircall API access."""

import json
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import FastMCP

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
