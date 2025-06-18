# mcp-server-kontomanager/src/mcp_server_kontomanager/models.py

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class UnitQuota(BaseModel):
    """Represents a usage quota for a specific unit (e.g., data, minutes)."""
    name: Optional[str] = None
    used: float
    total: float
    unit: str
    remaining: float
    unlimited: bool = False


class PackageUsage(BaseModel):
    """Represents the usage details for a specific tariff or package."""
    package_name: str
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    minutes: Optional[UnitQuota] = None
    sms: Optional[UnitQuota] = None
    data_domestic: Optional[UnitQuota] = None
    data_eu: Optional[UnitQuota] = None
    data_carried_over: Optional[UnitQuota] = None
    monthly_cost: Optional[float] = None


class AccountUsage(BaseModel):
    """The main model representing the overall account overview."""
    phone_number: str
    is_admin: bool = False
    is_prepaid: bool = False
    credit: Optional[float] = None
    sim_valid_until: Optional[date] = None
    last_recharge: Optional[date] = None
    current_costs: float
    next_bill_date: Optional[date] = None
    packages: List[PackageUsage]


class BillSummary(BaseModel):
    """A summary of a single bill, including URLs for retrieval."""
    bill_number: str
    date: date
    amount: float
    currency: str = "EUR"
    has_egn: bool
    bill_pdf_url: str
    egn_pdf_url: Optional[str] = None


class CallHistoryEntry(BaseModel):
    """A single entry in the call/SMS history."""
    timestamp: datetime
    type: str  # "Telefonat", "SMS"
    number: str
    duration: Optional[str] = None  # e.g., "0:02:12"
    cost: float


class SimSettings(BaseModel):
    """
    Represents the state of various SIM card settings.
    Field names are snake_cased versions of the API keys.
    """
    roaming_barred: Optional[bool] = None
    non_eu_roaming_barred: Optional[bool] = None
    roaming_sms_disable: Optional[bool] = None
    int_voice_barred: Optional[bool] = None
    international_sms_disable: Optional[bool] = None
    mpty_barred: Optional[bool] = None # MPTY = Multi-Party, i.e., Conference Calls
    premium_barred: Optional[bool] = None
    data_barred: Optional[bool] = None
    data_roaming_barred: Optional[bool] = None
    non_eu_data_roaming_barred: Optional[bool] = None


class CallForwardingRule(BaseModel):
    """Represents a single call forwarding rule."""
    condition: str
    target: str
    target_number: Optional[str] = None
    delay_seconds: Optional[int] = None


class CallForwardingSettings(BaseModel):
    """Represents all call forwarding settings for an account."""
    rules: List[CallForwardingRule]
    editable_on_phone: bool
    voicemail_play_cli_disable: bool


class PhoneNumber(BaseModel):
    """Represents a phone number associated with the account."""
    name: str
    number: str
    subscriber_id: Optional[str]
    is_active: bool
