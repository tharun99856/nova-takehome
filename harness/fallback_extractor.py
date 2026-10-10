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
            r'(?:INVOICE|Charges advice)\s+([A-Z]{2,3}[UI]?-\d{7,})',  # CDU-3051254, TX-US-2034-0379
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
        invoice_date = self._extract_date(text, r'(?:Invoice\s+date|Document date)\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})')
        if invoice_date and '/' in invoice_date:
            # Convert DD/MM/YYYY to YYYY-MM-DD
            parts = invoice_date.split('/')
            invoice_date = f'{parts[2]}-{parts[1]}-{parts[0]}'
        
        due_date = self._extract_date(text, r'(?:Due\s+date|Payable by)\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})')
        if due_date and '/' in due_date:
            parts = due_date.split('/')
            due_date = f'{parts[2]}-{parts[1]}-{parts[0]}'
        
        # Extract total amount
        total_match = re.search(r'(?:Total|Charges)\s+(?:USD|INR)\s+([\d,]+\.?\d{2})', text, re.IGNORECASE)
        total_amount = total_match.group(1).replace(',', '') if total_match else None
        
        # Extract supplier name
        supplier = None
        lines = text.split('\n')
        for line in lines[:5]:
            if re.search(r'\b(Inc\.|Ltd\.|Corp\.|LLC|Express)\b', line, re.IGNORECASE):
                supplier = line.strip()
                break
        
        # Extract contract reference
        contract_ref = None
        contract_match = re.search(r'Contract\s+(?:reference\s*:?\s*)?([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)', text, re.IGNORECASE)
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
            "contract_ref": contract_ref,
            "customer": None,
            "lines": lines_data,
            "_source_doc": doc_ref
        }
    
    def _extract_invoice_lines(self, text: str) -> list[dict]:
        """Extract invoice line items."""
        lines = []
        
        # Pattern for Caldrith exam format (date at end):
        # USE2-INS2 CA51959332 Air freight 299 kg 5.69 1,701.31 19/05/2030
        # USE2-INS2 CA51959332 Fuel surcharge 1,701.31 23.23% 395.21 19/05/2030
        pattern_exam = r'([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+([A-Z]{2}\d{8})\s+([A-Za-z\s]+?)\s+((?:\d+(?:\.\d+)?|[\d,]+\.?\d{2}))\s+(kg|shpt|days|%)\s+([\d.]+%?)\s+([\d,]+\.?\d{2})\s+(\d{2}/\d{2}/\d{4})'
        
        line_num = 1
        for match in re.finditer(pattern_exam, text):
            origin = match.group(1)
            dest = match.group(2)
            awb = match.group(3)
            charge_type = match.group(4).strip()
            qty = match.group(5).replace(',', '')
            basis = match.group(6)
            rate = match.group(7).replace('%', '')
            amount = match.group(8).replace(',', '')
            date_str = match.group(9)
            
            # Convert DD/MM/YYYY to YYYY-MM-DD
            parts = date_str.split('/')
            pickup_date = f'{parts[2]}-{parts[1]}-{parts[0]}'
            
            lines.append({
                "line_num": line_num,
                "awb": awb,
                "ship_date": pickup_date,
                "pickup_date": pickup_date,
                "origin": origin,
                "destination": dest,
                "weight_kg": qty if basis == "kg" else None,
                "pieces": qty if basis == "shpt" else None,
                "charge_type": charge_type,
                "rate": rate,
                "amount": amount,
                "description": f"{charge_type} {origin}-{dest}"
            })
            line_num += 1
        
        # If we found exam-style lines, return them
        if lines:
            return lines
        
        # Pattern 1: Standard line format with kg
        # 1 TX46602456 2034-11-17 Air freight USS2-INW2 299 kg 2.84 849.16
        pattern1 = r'(\d+)\s+([A-Z]{2}\d{8})\s+(\d{4}-\d{2}-\d{2})\s+([A-Za-z\s]+?)\s+([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+(\d+\.?\d*)\s+(kg|shpt)\s+([\d.]+)\s+([\d,]+\.?\d{2})'
        
        for match in re.finditer(pattern1, text):
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
                "description": f"{charge_type} {origin}-{dest} {qty} {basis}"
            })
        
        # Pattern 2: Percentage surcharges
        # 2 TX46602456 2034-11-17 Fuel surcharge USS2-INW2 849.16 18.38% 156.08
        pattern2 = r'(\d+)\s+([A-Z]{2}\d{8})\s+(\d{4}-\d{2}-\d{2})\s+([A-Za-z\s]+?surcharge)\s+([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+([\d,]+\.?\d{2})\s+([\d.]+)%\s+([\d,]+\.?\d{2})'
        
        for match in re.finditer(pattern2, text):
            line_num = int(match.group(1))
            if any(l['line_num'] == line_num for l in lines):
                continue
                
            awb = match.group(2)
            pickup_date = match.group(3)
            charge_type = match.group(4).strip()
            origin = match.group(5)
            dest = match.group(6)
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
                "description": f"{charge_type} {origin}-{dest}"
            })
        
        return lines
    
    def extract_contract_summary(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract contract summary."""
        if not pages:
            return None
        
        text = "\n".join(pages)
        
        # Extract contract ID
        contract_id = None
        for pattern in [
            r'Agreement\s+[Nn]o\.?\s*:?\s*([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)',
            r'Amendment\s+[Rr]eference\s+([A-Z]{3}-[A-Z]{2}-[A-Z]{3}[A-Z0-9/-]+)',
            r'([A-Z]{3}-[A-Z]{2}-[A-Z]{3}-[A-Z0-9]+)',
        ]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                contract_id = match.group(1)
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
        
        # Try multiple patterns for end date
        end_date = self._extract_date(text, r'[Ee]nd\s+[Dd]ate\s*:?\s*(\d{4}-\d{2}-\d{2})')
        if not end_date:
            end_date = self._extract_date(text, r'ending\s+on\s+(\d{4}-\d{2}-\d{2})')
        if not end_date:
            end_date = self._extract_date(text, r'expires?\s+(?:on\s+)?(\d{4}-\d{2}-\d{2})')
        
        # Extract parties
        parties = []
        
        # Look for "Company Name Inc. (the Carrier)"
        carrier_match = re.search(r'([A-Z][A-Za-z\s]+(?:Inc\.|Ltd\.|Corp\.|LLC|Express))\s*\(the\s+Carrier\)', text, re.IGNORECASE)
        if carrier_match:
            carrier_name = carrier_match.group(1).strip()
            parties.append({"name": carrier_name, "role": "carrier"})
        
        customer_match = re.search(r'([A-Z][A-Za-z\s]+(?:Inc\.|Ltd\.|Corp\.))\s*\(the\s+(?:Shipper|Customer)\)', text, re.IGNORECASE)
        if customer_match:
            customer_name = customer_match.group(1).strip()
            parties.append({"name": customer_name, "role": "customer"})
        
        # Check for rate table
        has_rate_table = bool(re.search(r'Annex\s+A|Rate\s+[Tt]able|Lane\s+Weight\s+.*Rate', text, re.IGNORECASE))
        
        # Check for rebate program
        has_rebate_program = bool(re.search(r'[Rr]ebate|[Vv]olume\s+[Ii]ncentive|[Qq]uarter.*[Ss]pend', text, re.IGNORECASE))
        rebate_tiers = []
        
        if has_rebate_program:
            # Extract rebate tiers from clause like "QS >= USD 55,000.00: 5%; QS >= USD 91,000.00: 7.5%"
            rebate_pattern = r'QS\s*>=?\s*USD\s*([\d,]+(?:\.\d+)?)\s*:\s*([\d.]+)%'
            for match in re.finditer(rebate_pattern, text, re.IGNORECASE):
                threshold = match.group(1).replace(',', '')
                percentage = match.group(2)
                rebate_tiers.append({
                    "threshold": threshold,
                    "percentage": percentage
                })
        
        # Determine contract type
        contract_type = "MSA"
        if "Amendment" in text or "AMD" in doc_ref.upper():
            contract_type = "Amendment"
        elif "MSA" in text or "Master Service Agreement" in text:
            contract_type = "MSA"
        
        # Extract Schedule 1 contacts
        schedule1_contacts = []
        # Pattern: Name, Title, Party: categories <email>
        contact_pattern = r'([A-Z][a-z]+\s+[A-Z][a-z]+),\s*([^,]+),\s*([A-Z-]+):\s*([^<]+)<([^>]+)>'
        for match in re.finditer(contact_pattern, text):
            name = match.group(1).strip()
            role = match.group(2).strip()
            party = match.group(3).strip()
            categories_str = match.group(4).strip()
            email = match.group(5).strip()
            
            # Parse categories (comma-separated)
            categories = [c.strip() for c in categories_str.split(',')]
            
            schedule1_contacts.append({
                "person": name,
                "role": role,
                "party": party,
                "categories": categories,
                "email": email
            })
        
        return {
            "contract_id": contract_id,
            "parties": parties,
            "effective_date": effective_date,
            "end_date": end_date,
            "contract_type": contract_type,
            "amends_contract": None,
            "schedule1_contacts": schedule1_contacts,
            "has_rate_table": has_rate_table,
            "has_fuel_table": bool(re.search(r'Annex\s+C|Fuel.*[Ss]urcharge\s+[Tt]able', text, re.IGNORECASE)),
            "has_rebate_program": has_rebate_program,
            "rebate_tiers": rebate_tiers if rebate_tiers else None,
            "_source_doc": doc_ref
        }
    
    def extract_rate_table(self, doc_text: str, doc_ref: str, pages: list[str], 
                          contract_id: str) -> list[dict]:
        """Extract rate tables."""
        rates = []
        
        for page_num, page_text in enumerate(pages, start=1):
            # USS2-INW2 0�44.5 kg 3.20
            pattern = r'([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+(\d+\.?\d*)[\u2013\-](\d+\.?\d*)\s+kg\s+([\d.]+)'
            
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
    
    def extract_fuel_surcharge_table(self, doc_text: str, doc_ref: str, pages: list[str], 
                                    contract_id: str) -> list[dict]:
        """Extract fuel surcharge table (Annex C)."""
        fuel_rates = []
        
        for page_num, page_text in enumerate(pages, start=1):
            # Look for fuel surcharge table patterns
            # Pattern: 2031-12 | 20.16%
            pattern = r'(\d{4}-\d{2})\s+(\d+\.\d+)%'
            
            for match in re.finditer(pattern, page_text):
                month = match.group(1)
                pct = match.group(2)
                
                fuel_rates.append({
                    "month": month,
                    "percentage": pct,
                    "page": page_num,
                    "_source_doc": doc_ref,
                    "_contract_id": contract_id
                })
        
        return fuel_rates
    
    def extract_tracking_export(self, doc_text: str, doc_ref: str, pages: list[str]) -> list[dict]:
        """Extract tracking events."""
        events = []
        if not pages:
            return events
        
        text = "\n".join(pages)
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
        
        if not re.search(r'\bwaiv(?:e|ed|ing)\b', text, re.IGNORECASE):
            return None
        
        awb_match = re.search(r'\b([A-Z]{2}\d{8})\b', text)
        awb = awb_match.group(1) if awb_match else None
        
        month_match = re.search(r'\b(\d{4}-\d{2})\b', text)
        month = month_match.group(1) if month_match else None
        
        sender_match = re.search(r'From:\s*([^\n<]+)', text)
        sender = sender_match.group(1).strip() if sender_match else None
        
        email_match = re.search(r'<([^>]+@[^>]+)>', text)
        sender_email = email_match.group(1) if email_match else None
        
        # Extract specific charge type from waiver text
        charge_type = None
        charge_patterns = [
            (r'Delivery\s+fee', 'Delivery fee'),
            (r'Fuel\s+surcharge', 'Fuel surcharge'),
            (r'Security\s+surcharge', 'Security surcharge'),
            (r'Peak\s+season\s+surcharge', 'Peak season surcharge'),
            (r'Air\s+freight', 'Air freight'),
        ]
        
        for pattern, name in charge_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                charge_type = name
                break
        
        # If no specific charge found, default to generic
        if not charge_type:
            charge_type = "surcharge"
        
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

