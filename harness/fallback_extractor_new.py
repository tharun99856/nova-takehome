"""Fallback deterministic extraction when API is not available."""
import re
import json
import sys
from decimal import Decimal


class FallbackExtractor:
    """Deterministic extraction using regex and pattern matching."""
    
    def extract_invoice(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract invoice using deterministic patterns."""
        if not pages:
            return None
            
        text = "\n".join(pages)
        
        # Extract invoice ID
        invoice_id = None
        for pattern in [
            r'INVOICE\s+([A-Z]{2,3}-[A-Z]{2}-\d{4}-\d{4})',
            r'Invoice[:\s]+([A-Z]{2,3}/\d{2}-\d{2}/\d{4})',
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                invoice_id = match.group(1).strip()
                break
        
        if not invoice_id:
            return None
        
        # Extract dates
        invoice_date = self._extract_date(text, r'Invoice\s+date\s+(\d{4}-\d{2}-\d{2})')
        due_date = self._extract_date(text, r'Due\s+date\s+(\d{4}-\d{2}-\d{2})')
        
        # Extract total amount
        total_match = re.search(r'Total\s+(?:USD|INR)\s+([\d,]+\.?\d{2})', text, re.IGNORECASE)
        total_amount = total_match.group(1).replace(',', '') if total_match else None
        
        # Extract supplier - FIXED
        supplier = None
        # Look for company name at top of invoice (first non-whitespace line or near INVOICE keyword)
        lines = text.split('\n')
        for line in lines[:5]:
            # Pattern: Company Name Inc./Ltd./Corp. etc at start of document
            if re.search(r'\b(Inc\.|Ltd\.|Corp\.|LLC|Express|Airways|Logistics)\b', line, re.IGNORECASE):
                supplier = line.strip()
                break
        
        # Extract contract reference - CRITICAL for matching
        contract_ref = None
        contract_match = re.search(r'Contract\s+reference\s*:?\s*([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)', text, re.IGNORECASE)
        if contract_match:
            contract_ref = contract_match.group(1)
        
        # Detect currency
        currency = "USD" if "USD" in text else ("INR" if "INR" in text else "USD")
        
        # Extract line items
        lines_data = self._extract_invoice_lines(text)
        
        return {
            "invoice_id": invoice_id,
            "invoice_date": invoice_date,
            "due_date": due_date,
            "currency": currency,
            "total_amount": total_amount,
            "supplier": supplier,
            "contract_ref": contract_ref,  # ADD THIS
            "customer": None,
            "lines": lines_data,
            "_source_doc": doc_ref
        }
    
    def _extract_invoice_lines(self, text: str) -> list[dict]:
        """Extract invoice line items."""
        lines = []
        
        # Pattern for line items in the actual format:
        # No. AWB Pickup Description Lane Qty / basis Rate Amount (USD)
        # 1 TX46602456 2034-11-17 Air freight USS2-INW2 299 kg 2.84 849.16
        
        # More flexible pattern
        pattern = r'(\d+)\s+([A-Z]{2}\d{8})\s+(\d{4}-\d{2}-\d{2})\s+([A-Za-z\s]+?)\s+([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+(\d+\.?\d*)\s+(kg|shpt)\s+([\d.]+)\s+([\d,]+\.?\d{2})'
        
        for match in re.finditer(pattern, text):
            line_num = int(match.group(1))
            awb = match.group(2)
            pickup_date = match.group(3)
            charge_type = match.group(4).strip()
            origin = match.group(5)
            dest = match.group(6)
            qty = match.group(7)
            basis = match.group(8)
            rate = match.group(9)
            amount = match.group(10).replace(',', '')
            
            lines.append({
                "line_num": line_num,
                "awb": awb,
                "ship_date": pickup_date,
                "pickup_date": pickup_date,
                "origin": origin,
                "destination": dest,
                "weight_kg": qty if basis == "kg" else None,
                "pieces": 1 if basis == "shpt" else None,
                "charge_type": charge_type,
                "rate": rate,
                "amount": amount,
                "description": f"{charge_type} {origin}-{dest} {qty} {basis} {rate} {amount}"
            })
        
        # Also handle percentage-based surcharges (no lane/weight)
        # 2 TX46602456 2034-11-17 Fuel surcharge USS2-INW2 849.16 18.38% 156.08
        perc_pattern = r'(\d+)\s+([A-Z]{2}\d{8})\s+(\d{4}-\d{2}-\d{2})\s+([A-Za-z\s]+?surcharge)\s+([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+([\d,]+\.?\d{2})\s+([\d.]+)%\s+([\d,]+\.?\d{2})'
        
        for match in re.finditer(perc_pattern, text):
            line_num = int(match.group(1))
            # Skip if we already added this line
            if any(l['line_num'] == line_num for l in lines):
                continue
                
            awb = match.group(2)
            pickup_date = match.group(3)
            charge_type = match.group(4).strip()
            origin = match.group(5)
            dest = match.group(6)
            base_amount = match.group(7).replace(',', '')
            rate_pct = match.group(8)
            amount = match.group(9).replace(',', '')
            
            lines.append({
                "line_num": line_num,
                "awb": awb,
                "ship_date": pickup_date,
                "pickup_date": pickup_date,
                "origin": origin,
                "destination": dest,
                "weight_kg": None,
                "pieces": None,
                "charge_type": charge_type,
                "rate": rate_pct,
                "amount": amount,
                "description": f"{charge_type} {origin}-{dest} {rate_pct}% {amount}"
            })
        
        return lines
    
    def extract_contract_summary(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract contract summary."""
        if not pages:
            return None
        
        text = "\n".join(pages)
        
        # Extract contract ID from text or filename
        contract_id = None
        for pattern in [
            r'Agreement\s+[Nn]o\.?\s*:?\s*([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)',
            r'Amendment\s+[Rr]eference\s+([A-Z]{3}-[A-Z]{2}-[A-Z]{3}[A-Z0-9/-]+)',
            r'Contract\s+reference\s*:?\s*([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)',
            r'([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)',
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                contract_id = match.group(1)
                # Remove /AMD-X suffix if present
                contract_id = re.sub(r'/AMD-\d+$', '', contract_id)
                break
        
        if not contract_id:
            # Try filename
            filename_match = re.search(r'([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)', doc_ref)
            if filename_match:
                contract_id = filename_match.group(1)
                contract_id = re.sub(r'-AMD-\d+$', '', contract_id)
        
        if not contract_id:
            return None
        
        # Extract dates
        effective_date = self._extract_date(text, r'Effective\s+(?:from|date)\s*:?\s*(\d{4}-\d{2}-\d{2})')
        end_date = self._extract_date(text, r'[Ee]nd\s+[Dd]ate\s*:?\s*(\d{4}-\d{2}-\d{2})')
        
        # Extract parties - FIXED
        parties = []
        
        # Look for "Company Name Inc. (the Carrier)" pattern
        carrier_patterns = [
            r'([A-Z][A-Za-z\s]+(?:Inc\.|Ltd\.|Corp\.|LLC|Express|Airways|Logistics))\s*\(the\s+Carrier\)',
            r'Carrier:?\s*([^\n(]+(?:Inc\.|Ltd\.|Corp\.))',
        ]
        for pattern in carrier_patterns:
            carrier_match = re.search(pattern, text, re.IGNORECASE)
            if carrier_match:
                carrier_name = carrier_match.group(1).strip()
                if carrier_name and len(carrier_name) > 3:
                    parties.append({"name": carrier_name, "role": "carrier"})
                    break
        
        customer_patterns = [
            r'([A-Z][A-Za-z\s]+(?:Inc\.|Ltd\.|Corp\.|LLC))\s*\(the\s+(?:Shipper|Customer)\)',
            r'Customer:?\s*([^\n(]+(?:Inc\.|Ltd\.|Corp\.))',
        ]
        for pattern in customer_patterns:
            customer_match = re.search(pattern, text, re.IGNORECASE)
            if customer_match:
                customer_name = customer_match.group(1).strip()
                if customer_name and len(customer_name) > 3:
                    parties.append({"name": customer_name, "role": "customer"})
                    break
        
        # Check for rate table
        has_rate_table = bool(re.search(r'Annex\s+A|Rate\s+[Tt]able|Lane\s+Weight\s+.*Rate', text, re.IGNORECASE))
        
        # Determine contract type
        contract_type = "MSA"
        if "Amendment" in text or "AMD" in doc_ref.upper():
            contract_type = "Amendment"
        elif "MSA" in text or "Master Service Agreement" in text:
            contract_type = "MSA"
        
        return {
            "contract_id": contract_id,
            "parties": parties,
            "effective_date": effective_date,
            "end_date": end_date,
            "contract_type": contract_type,
            "amends_contract": None,
            "schedule1_contacts": [],
            "has_rate_table": has_rate_table,
            "has_fuel_table": bool(re.search(r'Annex\s+C|Fuel.*[Ss]urcharge\s+[Tt]able', text, re.IGNORECASE)),
            "_source_doc": doc_ref
        }
    
    def extract_rate_table(self, doc_text: str, doc_ref: str, pages: list[str], 
                          contract_id: str) -> list[dict]:
        """Extract rate tables."""
        rates = []
        
        for page_num, page_text in enumerate(pages, start=1):
            # Pattern for rate rows in Annex A format:
            # Lane Weight bands and rates
            # USS2-INW2 0–44.5 kg 3.20
            
            pattern = r'([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+(\d+\.?\d*)[–\-](\d+\.?\d*)\s+kg\s+([\d.]+)'
            
            for match in re.finditer(pattern, page_text):
                origin = match.group(1)
                dest = match.group(2)
                weight_min = match.group(3)
                weight_max = match.group(4)
                rate = match.group(5)
                
                rates.append({
                    "lane": f"{origin}-{dest}",
                    "weight_min": weight_min,
                    "weight_max": weight_max,
                    "rate": rate,
                    "currency": "USD",
                    "effective_from": None,
                    "effective_to": None,
                    "page": page_num,
                    "_source_doc": doc_ref,
                    "_contract_id": contract_id
                })
        
        return rates
    
    def extract_tracking_export(self, doc_text: str, doc_ref: str, pages: list[str]) -> list[dict]:
        """Extract tracking events."""
        events = []
        
        if not pages:
            return events
        
        text = "\n".join(pages)
        
        # Pattern: AWB | EVENT | DATE | LOCATION
        pattern = r'([A-Z]{2}\d{8})\s*\|\s*([A-Z_]+)\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([A-Z]{3,4})'
        
        for match in re.finditer(pattern, text):
            events.append({
                "awb": match.group(1),
                "event": match.group(2),
                "event_date": match.group(3),
                "location": match.group(4),
                "notes": None,
                "_source_doc": doc_ref
            })
        
        return events
    
    def extract_payment_ledger(self, doc_text: str, doc_ref: str, pages: list[str]) -> list[dict]:
        """Extract payment register."""
        entries = []
        
        if not pages:
            return entries
        
        text = "\n".join(pages)
        
        # Pattern: INV-ID | DATE | due DATE | AMOUNT | STATUS | paid DATE
        pattern = r'([A-Z]{2,3}-[A-Z]{2}-\d{4}-\d{4}|[A-Z]{2,3}/\d{2}-\d{2}/\d{4})\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*due\s+(\d{4}-\d{2}-\d{2})\s*\|\s*(?:USD|INR)\s*([\d,]+\.?\d{2})\s*\|\s*(paid|unpaid|scheduled)\s*(?:\|\s*(\d{4}-\d{2}-\d{2}))?'
        
        for match in re.finditer(pattern, text, re.IGNORECASE):
            entries.append({
                "invoice_id": match.group(1),
                "invoice_date": match.group(2),
                "due_date": match.group(3),
                "amount": match.group(4).replace(',', ''),
                "currency": "USD",
                "status": match.group(5).lower(),
                "paid_date": match.group(6) if match.group(6) else None,
                "_source_doc": doc_ref
            })
        
        return entries
    
    def extract_waiver(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract waiver from email."""
        if not pages:
            return None
        
        text = "\n".join(pages)
        
        # Check for waiver keywords
        if not re.search(r'\bwaiv(?:e|ed|ing)\b', text, re.IGNORECASE):
            return None
        
        # Extract AWB if present
        awb_match = re.search(r'\b([A-Z]{2}\d{8})\b', text)
        awb = awb_match.group(1) if awb_match else None
        
        # Extract month if present (YYYY-MM format)
        month_match = re.search(r'\b(\d{4}-\d{2})\b', text)
        month = month_match.group(1) if month_match else None
        
        # Extract sender
        sender_match = re.search(r'From:\s*([^\n<]+)', text)
        sender = sender_match.group(1).strip() if sender_match else None
        
        email_match = re.search(r'<([^>]+@[^>]+)>', text)
        sender_email = email_match.group(1) if email_match else None
        
        # Determine charge type from context
        charge_type = "surcharge"
        if re.search(r'fuel', text, re.IGNORECASE):
            charge_type = "Fuel surcharge"
        elif re.search(r'security', text, re.IGNORECASE):
            charge_type = "Security surcharge"
        
        return {
            "awb": awb,
            "month": month,
            "charge_type": charge_type,
            "sender": sender,
            "sender_email": sender_email,
            "conditions": None,
            "_source_doc": doc_ref
        }
    
    def _extract_date(self, text: str, pattern: str) -> str | None:
        """Extract date using pattern."""
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    def find_evidence_quote(self, pages: list[str], search_text: str, min_length: int = 12) -> dict | None:
        """Find quote in pages."""
        search_norm = re.sub(r'\s+', ' ', search_text.lower().strip())
        
        for page_num, page_text in enumerate(pages, start=1):
            page_norm = re.sub(r'\s+', ' ', page_text.lower())
            
            if search_norm in page_norm:
                idx = page_norm.find(search_norm)
                if idx >= 0:
                    quote_start = max(0, idx - 10)
                    quote_end = min(len(page_text), idx + len(search_text) + 10)
                    quote = page_text[quote_start:quote_end].strip()
                    
                    non_space = len(re.sub(r'\s', '', quote))
                    if non_space >= min_length:
                        return {"page": page_num, "quote": quote}
        
        return None
