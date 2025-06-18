# mcp-server-kontomanager/src/server.py

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from mcp.server.fastmcp import Context, FastMCP, Image

from mcp_server_kontomanager.client import (KontomanagerClient,
                                            KontomanagerClientError)
from mcp_server_kontomanager.models import (AccountUsage, BillSummary,
                                            CallForwardingRule,
                                            CallForwardingSettings,
                                            CallHistoryEntry, PhoneNumber,
                                            SimSettings)
from mcp_server_kontomanager.settings import settings

# Setup logging
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[dict]:
    """Manages the lifecycle of the KontomanagerClient."""
    logger.info("MCP server starting up...")
    client = KontomanagerClient(settings)
    try:
        yield {"kontomanager_client": client}
    finally:
        await client.close()
        logger.info("MCP server shut down.")

mcp = FastMCP("Kontomanager", lifespan=lifespan)

def get_client() -> KontomanagerClient:
    """Helper to get the client instance from the context."""
    ctx: Context = mcp.get_context()
    return ctx.request_context.lifespan_context["kontomanager_client"]

def handle_client_error(e: KontomanagerClientError):
    """Helper to report client errors to the MCP context."""
    ctx: Context = mcp.get_context()
    logger.error(f"Kontomanager client error: {e}")
    ctx.error(str(e))
    raise e

### --- Tools (Tool-First Design) --- ###

# --- Data Retrieval Tools ---

@mcp.tool()
async def get_account_usage() -> AccountUsage:
    """Retrieves the main account overview, including plan details, usage statistics, and credit balance."""
    client = get_client()
    try:
        return await client.get_account_usage()
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def get_phone_numbers() -> List[PhoneNumber]:
    """Lists all phone numbers associated with the logged-in account."""
    client = get_client()
    try:
        return await client.get_phone_numbers()
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def list_bills() -> List[BillSummary]:
    """
    Fetches a list of available bills for the active number.
    This tool does NOT download the actual bill PDFs, it only lists their metadata.
    Use the `download_bill` tool to get the file content.
    """
    client = get_client()
    try:
        return await client.list_bills()
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def download_bill(bill_number: str, document_type: Literal['bill', 'egn'] = 'bill') -> Image:
    """
    Fetches a specific bill or its itemized record (EGN) and returns it as a PDF image/document.
    The binary PDF content is wrapped in an Image object for proper serialization.
    - bill_number: The number of the bill to download, found via `list_bills`.
    - document_type: 'bill' for the main invoice, 'egn' for the itemized record.
    """
    client = get_client()
    try:
        pdf_content = await client.get_bill(bill_number, document_type)
        logger.info(f"Successfully fetched {document_type} for bill '{bill_number}'.")
        # The Image helper class incorrectly assumes an "image/*" MIME type.
        # We instantiate it with the raw data and then manually override the
        # MIME type to the correct value for a PDF document.
        pdf_artifact = Image(data=pdf_content)
        pdf_artifact._mime_type = "application/pdf"
        return pdf_artifact
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def get_call_history() -> List[CallHistoryEntry]:
    """Retrieves a list of recent calls and SMS messages for the active number."""
    client = get_client()
    try:
        return await client.list_call_history()
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def get_sim_settings() -> SimSettings:
    """Reads the current state of all SIM-related settings (e.g., roaming status, data barring)."""
    client = get_client()
    try:
        return await client.get_sim_settings()
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def get_call_forwarding_settings() -> CallForwardingSettings:
    """Reads the current call forwarding and voicemail settings for the active number."""
    client = get_client()
    try:
        return await client.get_call_forwarding_settings()
    except KontomanagerClientError as e:
        handle_client_error(e)


# --- Action Tools ---

@mcp.tool()
async def switch_active_phone_number(subscriber_id: str) -> str:
    """
    Switches the server's active context to another phone number in the account group.
    Use `get_phone_numbers` to find the `subscriber_id` for other numbers.
    """
    client = get_client()
    try:
        return await client.switch_active_phone_number(subscriber_id)
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def set_sim_setting(setting_name: str, enabled: bool) -> str:
    """
    Enables or disables a specific SIM setting for the active number.
    Use `get_sim_settings` to see available setting keys (e.g., 'roaming_barred', 'data_barred').
    This is a low-level tool. For roaming, it's easier to use the `toggle_roaming` tool.
    """
    client = get_client()
    try:
        # The client's set_sim_setting expects the kebab-case key from the API.
        # This tool uses snake_case keys for consistency with the data models.
        api_key = setting_name.replace('_', '-')
        return await client.set_sim_setting(api_key, enabled)
    except KontomanagerClientError as e:
        handle_client_error(e)

@mcp.tool()
async def set_call_forwarding_rule(
    condition: Literal['alle', 'nann', 'wtel', 'nerr'],
    target: Literal['d', 'b', 'a'],
    target_number: Optional[str] = None,
    delay_seconds: Optional[Literal[5, 10, 15, 20, 25, 30]] = None,
) -> str:
    """
    Updates a specific call forwarding rule.
    - condition: The condition to change. 'alle' (all calls), 'nann' (no answer), 'wtel' (when busy), 'nerr' (not reachable).
    - target: The forwarding target. 'd' (deactivated), 'b' (voicemail/box), 'a' (another number).
    - target_number: The phone number to forward to (required if target is 'a'). Must be in international format, e.g., +43...
    - delay_seconds: The delay for 'nann' (no answer) condition.
    """
    client = get_client()
    if target == 'a' and not target_number:
        raise ValueError("target_number must be provided when target is 'a'.")

    if target_number and not re.match(r'^\+?\d{5,30}$', target_number):
        raise ValueError("Invalid target_number format. It should be a valid international phone number.")

    rule = CallForwardingRule(
        condition=condition, target=target, target_number=target_number, delay_seconds=delay_seconds
    )
    try:
        return await client.set_call_forwarding_rule(rule)
    except KontomanagerClientError as e:
        handle_client_error(e)


# --- Workflow Tools (Higher-Level Actions) ---

@mcp.tool()
async def toggle_roaming(enabled: bool) -> str:
    """
    A simplified tool to enable or disable international roaming.
    This is a high-level action that modifies the 'roaming_barred' SIM setting.
    """
    client = get_client()
    try:
        # enabled=True means roaming ON, which means roaming_barred must be FALSE.
        return await client.set_sim_setting("roaming-barred", not enabled)
    except KontomanagerClientError as e:
        handle_client_error(e)


# You can run this file directly for testing:
# KONTOMANAGER_BRAND=yesss KONTOMANAGER_USERNAME=... KONTOMANAGER_PASSWORD=... uv run python src/server.py
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
