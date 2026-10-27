"""Inbound MCP adapter for the R1 configuration application service.

The MCP stdio protocol does not establish an end-user identity. Callers must
bind a trusted principal when constructing this server; identity and tenant
are never accepted from tool arguments. This module does not expose HTTP MCP.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from ..configuration import (
    CONFIG_SCHEMA_VERSION,
    ConfigurationApplication,
    ConfigurationPrincipal,
)


class ConfigurationToolResponse(BaseModel):
    schema_version: str
    ok: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def create_configuration_mcp_server(
    application: ConfigurationApplication,
    *,
    principal: ConfigurationPrincipal,
) -> FastMCP:
    """Create an R1 stdio MCP server bound to one trusted principal."""
    server = FastMCP(
        "loomrise-configuration",
        instructions=(
            "Read configuration and create constrained draft/candidate changes. "
            "Candidates are not approved or published versions."
        ),
    )

    def execute(action: str, payload: dict[str, Any]) -> ConfigurationToolResponse:
        response = application.execute(
            principal=principal, action=action, payload=payload,
        )
        return ConfigurationToolResponse.model_validate(response)

    @server.tool(
        name="loomrise_draft_read",
        description="Read the current server-owned configuration draft and revision.",
        structured_output=True,
    )
    async def draft_read(agent_id: str) -> ConfigurationToolResponse:
        return execute("draft.get", {"agent_id": agent_id})

    @server.tool(
        name="loomrise_draft_create",
        description="Create a draft from a named stable configuration version.",
        structured_output=True,
    )
    async def draft_create(agent_id: str, base_version_id: str) -> ConfigurationToolResponse:
        return execute("draft.create", {
            "agent_id": agent_id,
            "base_version_id": base_version_id,
        })

    @server.tool(
        name="loomrise_draft_patch",
        description=(
            "Apply allowed field changes to a draft at an expected revision. "
            "External-agent field restrictions are enforced by the application service."
        ),
        structured_output=True,
    )
    async def draft_patch(
        agent_id: str,
        expected_revision: int,
        changes: list[dict[str, Any]],
    ) -> ConfigurationToolResponse:
        return execute("draft.patch", {
            "agent_id": agent_id,
            "expected_revision": expected_revision,
            "changes": changes,
        })

    @server.tool(
        name="loomrise_draft_validate",
        description="Validate a draft at its current or specified revision.",
        structured_output=True,
    )
    async def draft_validate(
        agent_id: str,
        expected_revision: int | None = None,
    ) -> ConfigurationToolResponse:
        payload: dict[str, Any] = {"agent_id": agent_id}
        if expected_revision is not None:
            payload["expected_revision"] = expected_revision
        return execute("draft.validate", payload)

    @server.tool(
        name="loomrise_candidate_freeze",
        description=(
            "Freeze a valid draft revision as an immutable candidate. "
            "This does not approve, publish, or change the stable version."
        ),
        structured_output=True,
    )
    async def candidate_freeze(
        agent_id: str,
        expected_revision: int,
        idempotency_key: str,
    ) -> ConfigurationToolResponse:
        return execute("candidate.freeze", {
            "agent_id": agent_id,
            "expected_revision": expected_revision,
            "idempotency_key": idempotency_key,
        })

    @server.tool(
        name="loomrise_candidate_read",
        description="Read an immutable candidate and its field-level diff.",
        structured_output=True,
    )
    async def candidate_read(agent_id: str, candidate_id: str) -> ConfigurationToolResponse:
        return execute("candidate.get", {
            "agent_id": agent_id,
            "candidate_id": candidate_id,
        })

    @server.tool(
        name="loomrise_candidate_list",
        description="List frozen candidates for an authorized expert.",
        structured_output=True,
    )
    async def candidate_list(agent_id: str) -> ConfigurationToolResponse:
        return execute("candidate.list", {"agent_id": agent_id})

    @server.tool(
        name="loomrise_stable_list",
        description="List immutable stable configuration versions for an authorized expert.",
        structured_output=True,
    )
    async def stable_list(agent_id: str) -> ConfigurationToolResponse:
        return execute("stable.list", {"agent_id": agent_id})

    @server.tool(
        name="loomrise_stable_read",
        description="Read an immutable stable configuration version.",
        structured_output=True,
    )
    async def stable_read(agent_id: str, version_id: str) -> ConfigurationToolResponse:
        return execute("stable.get", {"agent_id": agent_id, "version_id": version_id})

    @server.resource(
        "loomrise://agents/{agent_id}/draft",
        name="Configuration draft",
        description="Current draft snapshot for an authorized expert.",
        mime_type="application/json",
    )
    async def draft_resource(agent_id: str) -> str:
        response = execute("draft.get", {"agent_id": agent_id})
        return response.model_dump_json()

    @server.resource(
        "loomrise://agents/{agent_id}/candidates",
        name="Configuration candidates",
        description="Frozen candidates for an authorized expert.",
        mime_type="application/json",
    )
    async def candidate_list_resource(agent_id: str) -> str:
        response = execute("candidate.list", {"agent_id": agent_id})
        return response.model_dump_json()

    @server.resource(
        "loomrise://agents/{agent_id}/stable/{version_id}",
        name="Stable configuration version",
        description="Immutable configuration history for an authorized expert.",
        mime_type="application/json",
    )
    async def stable_resource(agent_id: str, version_id: str) -> str:
        response = execute("stable.get", {
            "agent_id": agent_id, "version_id": version_id,
        })
        return response.model_dump_json()

    return server


def run_configuration_mcp(
    application: ConfigurationApplication,
    *,
    principal: ConfigurationPrincipal,
) -> None:
    """Run the bound configuration MCP server over stdio only."""
    create_configuration_mcp_server(application, principal=principal).run("stdio")


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "ConfigurationToolResponse",
    "create_configuration_mcp_server",
    "run_configuration_mcp",
]
