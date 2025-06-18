# mcp-server-kontomanager/src/mcp_server_kontomanager/client.py

import logging
import re
from datetime import date, datetime
from typing import Dict, List
from urllib.parse import unquote, urljoin

import httpx
from parsel import Selector

from .models import (AccountUsage, BillSummary, CallForwardingRule,
                     CallForwardingSettings, CallHistoryEntry, PackageUsage,
                     PhoneNumber, SimSettings, UnitQuota)
from .settings import Settings

# Setup logging
logger = logging.getLogger(__name__)

class KontomanagerClientError(Exception):
    """Custom exception for client errors."""
    pass


class KontomanagerClient:
    """
    An asynchronous client to interact with the Kontomanager web interface.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._session: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self.settings.base_url,
            follow_redirects=True,
            timeout=30.0,
            cookies={"CookieSettings": '{"categories":["necessary"]}'}
        )
        self._logged_in = False
        self._excluded_sections = {
            "Ukraine Freieinheiten", "Ihre Kostenkontrolle", "TUR SYR Einheiten",
            "Verknüpfte Rufnummern", "Aktuelle Kosten", "Oft benutzt", "Gruppenfunktion"
        }

    async def close(self):
        """Closes the underlying HTTP session."""
        await self._session.aclose()

    async def _ensure_logged_in(self):
        """Ensures the client is logged in before making a request."""
        if not self._logged_in:
            await self.login()

    async def login(self):
        """Performs the login action."""
        logger.info(f"Attempting to log in as {self.settings.username} for brand {self.settings.brand}")
        try:
            await self._session.get("index.php")
            response = await self._session.post(
                "index.php",
                data={
                    "login_rufnummer": self.settings.username,
                    "login_passwort": self.settings.password,
                }
            )
            response.raise_for_status()
            sel = Selector(text=response.text)

            if sel.css("#loginform").get() or "Die eingegebenen Daten sind leider nicht korrekt" in response.text:
                error_message = sel.css('div[role="alert"] p strong::text').get() or "Invalid credentials"
                logger.error(f"Login failed for {self.settings.username}: {error_message}")
                raise KontomanagerClientError(f"Login failed: {error_message}")

            self._logged_in = True
            logger.info(f"Successfully logged in as {self.settings.username}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during login: {e.response.status_code} on {e.request.url}")
            raise KontomanagerClientError(f"HTTP error during login: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error(f"Network-related error during login: {e}")
            raise KontomanagerClientError(f"Network error during login: {e}") from e

    def _normalize_phone_number(self, number_str: str) -> str:
        """Consistently formats a phone number string to the E.164 standard for Austria."""
        if not number_str:
            return ""
        digits = re.sub(r'[^\d]', '', number_str)
        if not digits:
            return ""
        if digits.startswith('43'):
            return f"+{digits}"
        if digits.startswith('0'):
            return f"+43{digits[1:]}"
        return f"+43{digits}"

    def _parse_number(self, text: str, default: float = 0.0) -> float:
        """Parses a number from a string, handling German decimal formats."""
        if not text:
            return default
        cleaned_text = text.replace('€', '').replace('.', '').replace(',', '.').strip()
        match = re.search(r'[-+]?\d*\.?\d+', cleaned_text)
        return float(match.group(0)) if match else default

    def _parse_usage_bar(self, text: str) -> tuple[float, float, str]:
        """Parses the 'Verbraucht: X von Y (Einheit)' pattern."""
        match = re.search(r'Verbraucht:\s*([\d\.,]+)\s*\(von\s*([\d\.,]+|unlimited)\s*(\w+)\)?', text, re.IGNORECASE)
        if match:
            used = self._parse_number(match.group(1))
            total_str = match.group(2)
            total = float('inf') if total_str.lower() == 'unlimited' else self._parse_number(total_str)
            unit = match.group(3)
            return used, total, unit
        return 0.0, 0.0, ""

    async def get_account_usage(self) -> AccountUsage:
        """Fetches and parses the main account overview page."""
        await self._ensure_logged_in()
        logger.info("Fetching account usage data...")
        try:
            response = await self._session.get("kundendaten.php")
            response.raise_for_status()
            sel = Selector(text=response.text)

            # Determine account type (contract vs. prepaid)
            is_prepaid = "wertkarte" in sel.css("h1:first-of-type::text").get("").lower()

            raw_phone_text = sel.css("#user-dropdown span::text").get("").strip()
            is_admin = "admin" in raw_phone_text.lower()
            phone_number_part = raw_phone_text.split(' - ')[-1].strip()
            active_phone_number = self._normalize_phone_number(phone_number_part)

            # This will hold prepaid-specific data
            account_details = {"is_prepaid": is_prepaid, "credit": None, "sim_valid_until": None, "last_recharge": None}

            packages = []
            for card in sel.css("div.card"):
                title = card.css(".card-title::text").get("").strip().replace(":", "")
                if not title or title in self._excluded_sections:
                    continue

                # --- Handle Prepaid SIM Info Card ---
                if is_prepaid and title == "SIM Info":
                    total_credit = 0.0
                    for item in card.css(".list-group-item"):
                        text = " ".join(item.css("::text").getall()).strip()
                        if ":" not in text:
                            continue
                        key, value = [x.strip() for x in text.split(":", 1)]
                        key_lower = key.lower().strip()

                        if key_lower == "ihr aktuelles standardguthaben" or key_lower == "ihr aktuelles bonusguthaben":
                            total_credit += self._parse_number(value)
                        elif "letzte aufladung" in key_lower:
                            try:
                                account_details["last_recharge"] = datetime.strptime(value, "%d.%m.%Y").date()
                            except ValueError:
                                logger.warning(f"Could not parse last_recharge date: {value}")
                        elif "gültigkeit ihrer yesss! sim-karte" in key_lower:
                            try:
                                account_details["sim_valid_until"] = datetime.strptime(value, "%d.%m.%Y").date()
                            except ValueError:
                                logger.warning(f"Could not parse sim_valid_until date: {value}")
                    account_details["credit"] = total_credit
                    # Also add the base tariff name as a simple package
                    for item in card.css(".list-group-item .bold"):
                        text = item.css("::text").get("").strip()
                        if "tarif:" in text.lower():
                            packages.append(PackageUsage(package_name=text.split(":")[-1].strip()))
                    continue # This card is not a usage package, so skip to the next one

                # --- Handle Contract & Usage Package Cards ---
                package = PackageUsage(package_name=title)
                has_usage_data = False
                for item in card.css(".progress-item"):
                    heading = item.css(".progress-heading::text").get("").lower()
                    bar_right_text = item.css(".bar-label-right::text").get("")
                    used, total, unit = self._parse_usage_bar(bar_right_text)
                    if not unit:
                        continue
                    has_usage_data = True

                    quota = UnitQuota(used=used, total=total, unit=unit, remaining=total - used, unlimited=(total == float('inf')))
                    if "minuten/sms" in heading:
                        package.minutes = quota.copy(update={"unit": "Minutes/SMS"})
                        package.sms = quota.copy(update={"unit": "Minutes/SMS"})
                    elif "datenvolumen" in heading:
                        package.data_domestic = quota

                for detail_item in card.css(".collapse .list-group-item"):
                    text = " ".join(detail_item.css("::text").getall()).strip()
                    if ":" not in text:
                        continue

                    key, value = [x.strip() for x in text.split(":", 1)]
                    key_lower = key.lower().replace('&uuml;', 'ü')

                    if key_lower == "gültig von":
                        package.valid_from = datetime.strptime(value, "%d.%m.%Y %H:%M")
                    elif key_lower == "gültig bis":
                        package.valid_until = datetime.strptime(value, "%d.%m.%Y %H:%M")
                    elif key_lower == "gesamtkosten":
                        package.monthly_cost = self._parse_number(value)
                    elif 'preis' in key_lower and package.monthly_cost is None:
                        package.monthly_cost = self._parse_number(value)
                    elif key_lower == "datenvolumen eu verbleibend":
                        match = re.search(r'([\d\.,]+)\s*MB von ([\d\.,]+)\s*MB', value)
                        if match:
                            remaining_eu = self._parse_number(match.group(1))
                            total_eu = self._parse_number(match.group(2))
                            package.data_eu = UnitQuota(used=total_eu - remaining_eu, total=total_eu, unit="MB", remaining=remaining_eu)
                    elif key_lower == "datenmitnahme aus den vormonaten":
                        package.data_carried_over = UnitQuota(used=0, total=self._parse_number(value), unit="MB", remaining=self._parse_number(value))

                if has_usage_data:
                    packages.append(package)

            # --- Handle Costs Card (for both account types) ---
            current_costs = 0.0
            next_bill_date = None
            costs_card = sel.xpath("//h1[contains(text(), 'Aktuelle Kosten')]/ancestor::div[@class='card']")
            if costs_card:
                if is_prepaid:
                    cost_text = costs_card.css(".progress-heading::text").get("")
                    current_costs = self._parse_number(cost_text)
                else:  # Contract
                    for detail_item in costs_card.css(".collapse .list-group-item"):
                        text = " ".join(detail_item.css("::text").getall()).strip()
                        if ":" in text:
                            key, value = [x.strip() for x in text.split(":", 1)]
                            if "Vorläufige Kosten" in key:
                                current_costs = self._parse_number(value)
                            elif "Vorläufiges Rechnungsdatum" in key:
                                next_bill_date = datetime.strptime(value, "%d.%m.%Y").date()

            return AccountUsage(
                phone_number=active_phone_number, is_admin=is_admin,
                current_costs=current_costs, next_bill_date=next_bill_date, packages=packages,
                **account_details
            )
        except httpx.RequestError as e:
            raise KontomanagerClientError(f"HTTP error fetching account usage: {e}") from e
        except Exception as e:
            logger.exception("Failed to parse account usage page.")
            raise KontomanagerClientError(f"Failed to parse account usage: {e}") from e

    async def get_phone_numbers(self) -> List[PhoneNumber]:
        """Fetches the list of all phone numbers associated with the account."""
        await self._ensure_logged_in()
        logger.info("Fetching associated phone numbers...")
        response = await self._session.get("kundendaten.php")
        response.raise_for_status()
        sel = Selector(text=response.text)

        numbers = []

        active_item_selector = sel.xpath(".//h6[contains(text(), 'Aktuell gewählte Rufnummer:')]/parent::li/following-sibling::li[1]/a")
        if active_item_selector:
            name = active_item_selector.css("span.bold::text").get("").strip()
            number_raw = active_item_selector.xpath("./br/following-sibling::text()[1]").get("").strip()
            if name and number_raw:
                numbers.append(PhoneNumber(
                    name=name,
                    number=self._normalize_phone_number(number_raw),
                    subscriber_id=None,
                    is_active=True
                ))

        other_items_selectors = sel.xpath(".//h6[contains(text(), 'Rufnummer wechseln:')]/following-sibling::ul/li/a")
        for item_selector in other_items_selectors:
            name = item_selector.css("span.bold::text").get("").strip()
            number_raw = item_selector.xpath("./br/following-sibling::text()[1]").get("").strip()
            href = item_selector.attrib.get('href', '')
            sub_id_match = re.search(r'subscriber=([^&]+)', href)
            sub_id = unquote(sub_id_match.group(1)) if sub_id_match else None
            if name and number_raw:
                numbers.append(PhoneNumber(
                    name=name,
                    number=self._normalize_phone_number(number_raw),
                    subscriber_id=sub_id,
                    is_active=False
                ))

        if not numbers:
            logger.warning("Could not find any phone numbers in the dropdown.")
        return numbers

    async def switch_active_phone_number(self, subscriber_id: str) -> str:
        """Switches the active phone number for the session."""
        await self._ensure_logged_in()
        logger.info(f"Switching active number to subscriber ID: {subscriber_id}")
        response = await self._session.get(
            "kundendaten.php",
            params={"groupaction": "change_subscriber", "subscriber": subscriber_id}
        )
        response.raise_for_status()
        sel = Selector(text=response.text)
        raw_phone_text = sel.css("#user-dropdown span::text").get("").strip()
        new_active_number = self._normalize_phone_number(raw_phone_text.split(' - ')[-1].strip())
        return f"Successfully switched active number to {new_active_number}."

    async def list_bills(self) -> List[BillSummary]:
        """Fetches the list of available bills from the 'rechnungen.php' page."""
        await self._ensure_logged_in()
        logger.info("Fetching list of bills from 'rechnungen.php'...")
        try:
            response = await self._session.get("rechnungen.php")
            response.raise_for_status()
            sel = Selector(text=response.text)

            bills = []
            for row in sel.xpath('//ul[@class="list-group mt-3"]'):
                date_raw = row.xpath("li[1]/div/div[2]/text()").get("").strip()
                bill_date = datetime.strptime(date_raw, "%d.%m.%Y").date() if date_raw else date.today()

                bill_pdf_url = row.xpath("li[4]/div/div/a/@href").get()
                egn_pdf_url = row.xpath("li[5]/div/div/a/@href").get()

                if not bill_pdf_url:
                    logger.warning(f"Skipping a bill entry from {bill_date} because no PDF URL was found.")
                    continue

                bill_item = BillSummary(
                    date=bill_date,
                    amount=self._parse_number(row.xpath("li[2]/div/div[2]/text()").get("")),
                    bill_number=row.xpath("li[3]/div/div[2]/text()").get("").strip(),
                    bill_pdf_url=urljoin(self.settings.base_url, bill_pdf_url),
                    egn_pdf_url=urljoin(self.settings.base_url, egn_pdf_url) if egn_pdf_url else None,
                    has_egn=bool(egn_pdf_url)
                )
                bills.append(bill_item)

            if not bills:
                logger.warning("No bills found on the page. The layout might have changed or there are no bills.")

            return bills
        except httpx.RequestError as e:
            raise KontomanagerClientError(f"HTTP error fetching bills list: {e}") from e
        except Exception as e:
            logger.exception("Failed to parse bills page.")
            raise KontomanagerClientError(f"Failed to parse bills list: {e}") from e

    async def get_bill(self, bill_number: str, bill_type: str) -> bytes:
        """Fetches the PDF content for a given bill number and type."""
        if bill_type.lower() not in ['bill', 'egn']:
            raise KontomanagerClientError(f"Invalid bill_type: '{bill_type}'. Must be 'bill' or 'egn'.")

        await self._ensure_logged_in()
        logger.info(f"Attempting to retrieve {bill_type} for bill number {bill_number}...")

        bills = await self.list_bills()
        target_bill = next((b for b in bills if b.bill_number == bill_number), None)

        if not target_bill:
            raise KontomanagerClientError(f"Bill with number '{bill_number}' not found.")

        url_to_fetch = target_bill.bill_pdf_url if bill_type.lower() == 'bill' else target_bill.egn_pdf_url

        if not url_to_fetch:
            raise KontomanagerClientError(f"Document type '{bill_type}' is not available for bill {bill_number}.")

        logger.info(f"Fetching PDF from URL: {url_to_fetch}")
        try:
            response = await self._session.get(url_to_fetch)
            response.raise_for_status()

            if 'application/pdf' not in response.headers.get('content-type', ''):
                logger.warning(f"Expected a PDF but got content-type: {response.headers.get('content-type')}.")

            return response.content
        except httpx.HTTPStatusError as e:
            raise KontomanagerClientError(f"HTTP error {e.response.status_code} fetching PDF for bill {bill_number}.") from e
        except httpx.RequestError as e:
            raise KontomanagerClientError(f"Network error fetching PDF for bill {bill_number}: {e}") from e

    async def list_call_history(self) -> List[CallHistoryEntry]:
        """Fetches the call and SMS history."""
        await self._ensure_logged_in()
        logger.info("Fetching call history...")
        response = await self._session.get("gespraeche.php")
        response.raise_for_status()
        sel = Selector(text=response.text)

        history = []
        # Iterate over each call history block
        for item in sel.css("ul.list-group.mt-3"):
            # First, build a dictionary of all data for this block
            data: Dict[str, str] = {}
            for row in item.css("li.list-group-item"):
                key_node = row.css(".bold::text")
                if not key_node:
                    continue
                key = key_node.get("").replace(":", "").strip().lower()
                # The value is in the second `div` inside the `div.row`
                value_node = row.xpath("div/div[2]/text()")
                value = value_node.get("").strip()
                data[key] = value

            # Now that the block is parsed, validate and process it
            timestamp_str = data.get("datum/uhrzeit")
            if not timestamp_str:
                logger.warning("Skipping a call history item because its timestamp is missing.")
                continue

            dauer_kosten_str = data.get("dauer/kosten", "")
            parts = dauer_kosten_str.split('/')
            duration = parts[0].strip() if parts else "0:00:00"
            cost_str = parts[1].strip() if len(parts) > 1 else "0"

            try:
                entry = CallHistoryEntry(
                    timestamp=datetime.strptime(timestamp_str, "%d.%m.%Y %H:%M:%S"),
                    type=data.get("art", "Unbekannt"),
                    number=data.get("nummer", ""),
                    duration=duration,
                    cost=self._parse_number(cost_str)
                )
                history.append(entry)
            except ValueError:
                logger.warning(f"Could not parse date for call history item: '{timestamp_str}'. Skipping.")
                continue

        return history

    async def get_sim_settings(self) -> SimSettings:
        """Fetches the current SIM settings."""
        await self._ensure_logged_in()
        logger.info("Fetching SIM settings from JSON API...")
        response = await self._session.post("einstellungen_sim_getdata.php")
        response.raise_for_status()
        api_response = response.json()

        if api_response.get("status") != "OK":
            raise KontomanagerClientError(f"SIM settings API returned an error: {api_response}")

        settings_data = {}
        for item in api_response.get("data", []):
            # Convert kebab-case from API to snake_case for the Pydantic model
            key = item.get("key", "").replace('-', '_')
            # Ensure we only try to map keys that exist in our model
            if key in SimSettings.model_fields:
                settings_data[key] = item.get("value", False)
        return SimSettings(**settings_data)

    async def set_sim_setting(self, setting_name: str, enabled: bool) -> str:
        """Changes a SIM setting."""
        await self._ensure_logged_in()
        logger.info(f"Setting SIM setting '{setting_name}' to enabled={enabled}")

        # First, we need to get a CSRF token from the main settings page
        form_page_res = await self._session.get("einstellungen_sim.php")
        form_page_res.raise_for_status()
        sel = Selector(text=form_page_res.text)
        token = sel.css("input[name='token']::attr(value)").get()
        if not token:
            raise KontomanagerClientError("Could not find CSRF token to change SIM settings.")

        payload = {
            "key": setting_name.replace('_', '-'), # API expects kebab-case
            "value": 't' if enabled else 'f', # API uses 't'/'f' for boolean
            "token": token
        }
        response = await self._session.post("einstellungen_sim_setdata.php", data=payload)
        response.raise_for_status()

        if response.text.strip().upper() != "OK":
            raise KontomanagerClientError(f"Failed to set '{setting_name}'. API response: {response.text}")
        return f"Successfully set '{setting_name}' to {'enabled' if enabled else 'disabled'}."

    async def get_call_forwarding_settings(self) -> CallForwardingSettings:
        """Fetches the current call forwarding settings from 'einstellungen_rufumleitung.php'."""
        await self._ensure_logged_in()
        logger.info("Fetching call forwarding settings...")
        response = await self._session.get("einstellungen_rufumleitung.php")
        response.raise_for_status()
        sel = Selector(text=response.text)

        rules = []
        rule_ids = ["alle", "nann", "wtel", "nerr"]
        for rid in rule_ids:
            target = sel.css(f"select[name='{rid}_akt'] option[selected='selected']::attr(value)").get()
            if not target: # Fallback if no 'selected' attribute is found
                 target = sel.css(f"select[name='{rid}_akt']::attr(value)").get('d')

            target_number = sel.css(f"input[name='{rid}_rn']::attr(value)").get() if target == 'a' else None
            delay_seconds = None
            if rid == 'nann':
                delay_str = sel.css("select[name='nann_sek'] option[selected='selected']::attr(value)").get()
                if not delay_str:
                    delay_str = sel.css("select[name='nann_sek']::attr(value)").get('25')
                delay_seconds = int(delay_str) if delay_str and delay_str.isdigit() else None

            rules.append(CallForwardingRule(
                condition=rid,
                target=target,
                target_number=target_number,
                delay_seconds=delay_seconds
            ))

        editable_on_phone_val = sel.css("select[name='btel_akt'] option[selected='selected']::attr(value)").get('d')
        voicemail_play_cli_val = sel.css("select[name='voicemail_play_cli_disable'] option[selected='selected']::attr(value)").get('d')

        return CallForwardingSettings(
            rules=rules,
            editable_on_phone=(editable_on_phone_val == 'a'), # 'a' means enabled
            voicemail_play_cli_disable=(voicemail_play_cli_val == 'd') # 'd' means disabled is true
        )

    async def set_call_forwarding_rule(self, rule_to_set: CallForwardingRule) -> str:
        """Sets a single call forwarding rule by fetching the current state and submitting the entire form."""
        await self._ensure_logged_in()
        logger.info(f"Setting call forwarding for condition '{rule_to_set.condition}'...")

        # Get the current settings to build the full payload
        current_settings = await self.get_call_forwarding_settings()

        # Get a fresh CSRF token
        response = await self._session.get("einstellungen_rufumleitung.php")
        response.raise_for_status()
        sel = Selector(text=response.text)
        token = sel.css("input[name='token']::attr(value)").get()
        if not token:
            raise KontomanagerClientError("Could not find CSRF token for call forwarding.")

        payload: Dict[str, str] = {"dosubmit": "1", "token": token}

        # Populate payload with all rules, replacing the one we want to change
        for rule in current_settings.rules:
            rule_to_apply = rule_to_set if rule.condition == rule_to_set.condition else rule
            payload[f"{rule_to_apply.condition}_akt"] = rule_to_apply.target
            if rule_to_apply.target_number:
                payload[f"{rule_to_apply.condition}_rn"] = rule_to_apply.target_number
            # The delay field is always submitted for the 'nann' rule
            if rule_to_apply.condition == 'nann' and rule_to_apply.delay_seconds is not None:
                payload["nann_sek"] = str(rule_to_apply.delay_seconds)

        payload["btel_akt"] = 'a' if current_settings.editable_on_phone else 'd'
        payload["voicemail_play_cli_disable"] = 'a' if current_settings.voicemail_play_cli_disable else 'd'

        post_response = await self._session.post("einstellungen_rufumleitung.php", data=payload)
        post_response.raise_for_status()

        if "Fehler" in post_response.text or "error" in post_response.text.lower():
             raise KontomanagerClientError("Failed to set call forwarding rule. The server reported an error.")

        return f"Successfully updated call forwarding rule for condition '{rule_to_set.condition}'."
