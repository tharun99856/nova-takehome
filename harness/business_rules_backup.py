"""Business rules for finding detection with deterministic logic."""
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, date
from typing import Any


def normalize_invoice_id(invoice_id: str) -> str:
    """Normalize invoice ID per GLOSSARY: uppercase, remove spaces/#/:"""
    if not invoice_id:
        return ""
    return re.sub(r'[\s#:]', '', str(invoice_id)).upper()


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    """Round half up to specified decimal places."""
    quantizer = Decimal(10) ** -places
    return value.quantize(quantizer, rounding=ROUND_HALF_UP)


def parse_decimal(value: Any) -> Decimal | None:
    """Safely parse to Decimal."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except:
        return None


def parse_date(value: Any) -> date | None:
    """Safely parse ISO date string."""
    if not value:
        return None
    try:
        if isinstance(value, date):
            return value
        return datetime.fromisoformat(str(value).split('T')[0]).date()
    except:
        return None


class OverchargeDetector:
    """Detect overcharges using contract rates and deterministic calculations."""
    
    def __init__(self, state):
        self.state = state
    
    def detect_overcharges(self, as_of: str) -> list[dict]:
        """Find all overcharges up to as_of date."""
        findings = []
        
        # Get invoices
        invoices = self.state.get_entities("invoice", as_of=as_of)
        
        # Get contracts and rates
        contracts = self.state.get_entities("contract", as_of=as_of)
        rates = self.state.get_entities("rate", as_of=as_of)
        
        # Build contract lookup
        contract_map = {}
        for c in contracts:
            data = c.get("data")
            if isinstance(data, str):
                import json
                data = json.loads(data)
            cid = data.get("contract_id")
            if cid:
                contract_map[cid] = data
        
        # Build rate lookup by contract + lane
        rate_map = {}  # (contract_id, lane) -> [rates]
        for r in rates:
            data = r.get("data")
            if isinstance(data, str):
                import json
                data = json.loads(data)
            cid = data.get("_contract_id")
            lane = data.get("lane")
            if cid and lane:
                key = (cid, lane)
                if key not in rate_map:
                    rate_map[key] = []
                rate_map[key].append(data)
        
        # Check each invoice
        for inv in invoices:
            data = inv.get("data")
            if isinstance(data, str):
                import json
                data = json.loads(data)
            
            invoice_id = data.get("invoice_id")
            if not invoice_id:
                continue
            
            # Try to find contract (simplified - would need smarter matching)
            contract_id = self._find_contract_for_invoice(data, contract_map)
            if not contract_id:
                continue
            
            # Check each line
            for line in data.get("lines", []):
                finding = self._check_line_overcharge(
                    invoice_id, line, contract_id, rate_map, data, as_of
                )
                if finding:
                    findings.append(finding)
        
        return findings
    
    def _find_contract_for_invoice(self, invoice_data: dict, contract_map: dict) -> str | None:
        """Match invoice to contract (simplified heuristic)."""
        # Look for contract reference in supplier name or customer
        supplier = str(invoice_data.get("supplier", "")).upper()
        
        # Simple heuristic: match carrier name
        for cid, contract in contract_map.items():
            for party in contract.get("parties", []):
                if party.get("role") == "carrier":
                    carrier_name = str(party.get("name", "")).upper()
                    # Simple substring match
                    if carrier_name and len(carrier_name) > 3:
                        if carrier_name[:3] in supplier or supplier[:3] in carrier_name:
                            return cid
        
        return None
    
    def _check_line_overcharge(self, invoice_id: str, line: dict, contract_id: str,
                                rate_map: dict, invoice_data: dict, as_of: str) -> dict | None:
        """Check if a line is overcharged."""
        
        # Extract line details
        origin = line.get("origin")
        dest = line.get("destination")
        if not origin or not dest:
            return None
        
        lane = f"{origin}-{dest}"
        weight_kg = parse_decimal(line.get("weight_kg"))
        if not weight_kg:
            return None
        
        billed_amount = parse_decimal(line.get("amount"))
        if not billed_amount:
            return None
        
        # Get applicable rate
        applicable_rate = self._find_applicable_rate(
            contract_id, lane, weight_kg, line, rate_map, invoice_data
        )
        
        if not applicable_rate:
            return None  # Cannot determine without rate
        
        # Calculate correct amount
        rate_value = parse_decimal(applicable_rate.get("rate"))
        if not rate_value:
            return None
        
        correct_amount = round_half_up(rate_value * weight_kg)
        
        # Check for overcharge
        overcharge = billed_amount - correct_amount
        
        if overcharge > Decimal("0.01"):  # More than tolerance
            # Build finding
            norm_inv_id = normalize_invoice_id(invoice_id)
            finding_key = f"overcharge:{norm_inv_id}"
            
            # Build evidence
            evidence = []
            
            # Invoice line evidence
            line_desc = line.get("description", "")
            if line_desc:
                evidence.append({
                    "doc": invoice_data.get("_source_doc"),
                    "page": 1,
                    "quote": line_desc[:100]  # First 100 chars
                })
            
            # Rate evidence
            rate_doc = applicable_rate.get("_source_doc")
            if rate_doc:
                # Find quote for rate
                rate_quote = f"{lane} {applicable_rate.get('weight_min')}-{applicable_rate.get('weight_max')} kg {applicable_rate.get('rate')}"
                evidence.append({
                    "doc": rate_doc,
                    "page": applicable_rate.get("page", 1),
                    "quote": rate_quote
                })
            
            return {
                "finding_key": finding_key,
                "class": "overcharge",
                "invoice_id": invoice_id,
                "verdict": "finding",
                "amount_usd": str(round_half_up(overcharge)),
                "action": "draft:dispute",
                "confidence": 0.85,
                "evidence": evidence,
                "data": {
                    "line": line,
                    "billed": str(billed_amount),
                    "correct": str(correct_amount),
                    "overcharge": str(overcharge),
                    "rate_used": applicable_rate
                }
            }
        
        return None
    
    def _find_applicable_rate(self, contract_id: str, lane: str, weight_kg: Decimal,
                             line: dict, rate_map: dict, invoice_data: dict) -> dict | None:
        """Find the applicable rate for a shipment."""
        
        # Get pickup date (priority: tracking > pickup email > AWB > invoice ship date)
        pickup_date = self._resolve_pickup_date(line, invoice_data)
        if not pickup_date:
            return None
        
        # Get rates for this contract + lane
        key = (contract_id, lane)
        rates = rate_map.get(key, [])
        
        if not rates:
            return None
        
        # Filter by weight bracket
        applicable = []
        for rate in rates:
            weight_min = parse_decimal(rate.get("weight_min"))
            weight_max = parse_decimal(rate.get("weight_max"))
            
            if weight_min is None or weight_max is None:
                continue
            
            # Check if weight falls in bracket
            if weight_min <= weight_kg <= weight_max:
                # Check if rate was effective on pickup date
                effective_from = parse_date(rate.get("effective_from"))
                effective_to = parse_date(rate.get("effective_to"))
                
                if effective_from and pickup_date < effective_from:
                    continue
                if effective_to and pickup_date > effective_to:
                    continue
                
                applicable.append(rate)
        
        # Return first applicable (would need precedence logic for amendments)
        return applicable[0] if applicable else None
    
    def _resolve_pickup_date(self, line: dict, invoice_data: dict) -> date | None:
        """Resolve pickup date per GLOSSARY priority."""
        # 1. Tracking export (would need separate entity)
        # 2. Pickup email (would need separate entity)
        # 3. AWB date (not in line currently)
        # 4. Ship date from invoice
        
        # For now, use line pickup_date or ship_date
        pickup = parse_date(line.get("pickup_date"))
        if pickup:
            return pickup
        
        ship = parse_date(line.get("ship_date"))
        if ship:
            return ship
        
        # Fall back to invoice date
        return parse_date(invoice_data.get("invoice_date"))
