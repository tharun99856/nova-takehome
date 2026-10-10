"""Entity extraction using Groq API with structured outputs."""
import json
import os
import re
import sys
from typing import Any


class ClaudeExtractor:
    """Extract structured entities using Groq API."""
    
    def __init__(self):
        api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        
        if api_key:
            # Use Groq with OpenAI-compatible API
            try:
                from openai import OpenAI
                self.client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.groq.com/openai/v1"
                )
                self.model = "llama-3.3-70b-specdec"  # Latest available Llama model
                self.use_api = True
            except ImportError:
                print("openai package not available, using fallback", file=sys.stderr)
                self.use_api = False
        else:
            print("GROQ_API_KEY not set, using fallback extraction", file=sys.stderr)
            self.use_api = False
        
        # Always have fallback available
        from fallback_extractor import FallbackExtractor
        self.fallback = FallbackExtractor()
    
    def extract_invoice(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract invoice header and line items with evidence."""
        
        if not self.use_api:
            return self.fallback.extract_invoice(doc_text, doc_ref, pages)
        
        # Combine pages for context (limit to save tokens)
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages[:3])  # First 3 pages
        )
        
        # Truncate if too long
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n... [truncated]"
        
        prompt = f"""Extract invoice information from this document. Return ONLY valid JSON with NO markdown.

Document: {doc_ref}

{full_text}

Extract:
{{
  "invoice_id": "exact ID as printed (with spaces/# if present)",
  "invoice_date": "YYYY-MM-DD",
  "currency": "USD or INR",
  "total_amount": "decimal string",
  "supplier": "carrier/supplier name",
  "customer": "customer name",
  "lines": [
    {{
      "line_num": 1,
      "awb": "airway bill number or null",
      "ship_date": "YYYY-MM-DD or null",
      "pickup_date": "YYYY-MM-DD or null",
      "origin": "3-letter code",
      "destination": "3-letter code", 
      "weight_kg": "decimal string",
      "pieces": "integer or null",
      "charge_type": "Air freight/Fuel surcharge/etc",
      "rate": "decimal string or null",
      "amount": "decimal string",
      "description": "full line description"
    }}
  ]
}}

Rules:
- Extract exact text from document
- Convert dates to YYYY-MM-DD format
- Use null for missing fields
- Return empty lines array if no line items found"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=3000
            )
            
            text = response.choices[0].message.content
            
            # Clean markdown if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            data["_source_doc"] = doc_ref
            return data
            
        except Exception as e:
            print(f"API extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_invoice(doc_text, doc_ref, pages)
    
    def extract_contract_summary(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract key contract terms."""
        
        if not self.use_api:
            return self.fallback.extract_contract_summary(doc_text, doc_ref, pages)
        
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages[:5])
        )
        
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n... [truncated]"
        
        prompt = f"""Extract contract information. Return ONLY valid JSON with NO markdown.

Document: {doc_ref}

{full_text}

Extract:
{{
  "contract_id": "contract reference",
  "parties": [{{"name": "party name", "role": "carrier/customer"}}],
  "effective_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD or null",
  "contract_type": "MSA/Amendment/etc",
  "amends_contract": "parent contract ID if amendment, else null",
  "schedule1_contacts": [
    {{
      "person": "full name",
      "role": "job title", 
      "categories": ["rates", "waivers", "payment_terms", "notices", "billing_disputes"],
      "email": "email if present or null"
    }}
  ],
  "has_rate_table": true,
  "has_fuel_table": false
}}

Use null for missing fields. If you see rate tables or fuel tables, set the flags to true."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=2000
            )
            
            text = response.choices[0].message.content
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            data["_source_doc"] = doc_ref
            return data
            
        except Exception as e:
            print(f"Contract extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_contract_summary(doc_text, doc_ref, pages)
    
    def extract_rate_table(self, doc_text: str, doc_ref: str, pages: list[str], 
                          contract_id: str) -> list[dict]:
        """Extract rate tables from contract pages."""
        
        if not self.use_api:
            return self.fallback.extract_rate_table(doc_text, doc_ref, pages, contract_id)
    
    def extract_fuel_surcharge_table(self, doc_text: str, doc_ref: str, pages: list[str], 
                                    contract_id: str) -> list[dict]:
        """Extract fuel surcharge tables from contract pages."""
        
        # Always use fallback for now (fuel table extraction is simple pattern matching)
        return self.fallback.extract_fuel_surcharge_table(doc_text, doc_ref, pages, contract_id)
        
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages)
        )
        
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n... [truncated]"
        
        prompt = f"""Extract ALL rate table entries. Return ONLY valid JSON array with NO markdown.

Contract: {contract_id}
Document: {doc_ref}

{full_text}

Extract each rate as JSON array:
[
  {{
    "lane": "ORIGIN-DEST format (e.g., USE2-INE2)",
    "weight_min": "decimal string (kg)",
    "weight_max": "decimal string (kg)",
    "rate": "decimal string per kg",
    "currency": "USD/INR",
    "effective_from": null,
    "effective_to": null,
    "page": page_number
  }}
]

Rules:
- Extract every rate row you find
- Use exact numeric strings
- Include weight bands (e.g., 0-44.5, 45-99.5, 100-299.5)
- Return empty array [] if no rates found"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=3000
            )
            
            text = response.choices[0].message.content
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            rates = json.loads(text)
            if not isinstance(rates, list):
                return []
            
            for rate in rates:
                rate["_source_doc"] = doc_ref
                rate["_contract_id"] = contract_id
            
            return rates
            
        except Exception as e:
            print(f"Rate table extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_rate_table(doc_text, doc_ref, pages, contract_id)
    
    
    def extract_tracking_export(self, doc_text: str, doc_ref: str, pages: list[str]) -> list[dict]:
        """Extract tracking events from Excel export."""
        
        if not self.use_api:
            return self.fallback.extract_tracking_export(doc_text, doc_ref, pages)
        
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages[:3])
        )
        
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n... [truncated]"
        
        prompt = f"""Extract tracking events from this export. Return ONLY valid JSON array with NO markdown.

Document: {doc_ref}

{full_text}

Extract each tracking event:
[
  {{
    "awb": "airway bill number",
    "event": "PICKED_UP",
    "event_date": "YYYY-MM-DD",
    "location": "3-letter code",
    "notes": "any additional info or null"
  }}
]

Focus on PICKED_UP events. Return empty array [] if no tracking data found."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=2000
            )
            
            text = response.choices[0].message.content
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            events = json.loads(text)
            if not isinstance(events, list):
                return []
            
            for event in events:
                event["_source_doc"] = doc_ref
            
            return events
            
        except Exception as e:
            print(f"Tracking extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_tracking_export(doc_text, doc_ref, pages)
    
    def extract_payment_ledger(self, doc_text: str, doc_ref: str, pages: list[str]) -> list[dict]:
        """Extract payment register entries."""
        
        if not self.use_api:
            return self.fallback.extract_payment_ledger(doc_text, doc_ref, pages)
        
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages[:3])
        )
        
        if len(full_text) > 15000:
            full_text = full_text[:15000] + "\n... [truncated]"
        
        prompt = f"""Extract AP register/payment ledger entries. Return ONLY valid JSON array with NO markdown.

Document: {doc_ref}

{full_text}

Extract each entry:
[
  {{
    "invoice_id": "as printed",
    "invoice_date": "YYYY-MM-DD",
    "due_date": "YYYY-MM-DD",
    "amount": "decimal string",
    "currency": "USD/INR",
    "status": "paid/unpaid/scheduled",
    "paid_date": "YYYY-MM-DD or null"
  }}
]

Return empty array [] if not a payment register."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=2000
            )
            
            text = response.choices[0].message.content
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            entries = json.loads(text)
            if not isinstance(entries, list):
                return []
            
            for entry in entries:
                entry["_source_doc"] = doc_ref
            
            return entries
            
        except Exception as e:
            print(f"Payment ledger extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_payment_ledger(doc_text, doc_ref, pages)
    
    def extract_waiver(self, doc_text: str, doc_ref: str, pages: list[str]) -> dict | None:
        """Extract waiver information from email."""
        
        if not self.use_api:
            return self.fallback.extract_waiver(doc_text, doc_ref, pages)
        
        full_text = "\n\n=== PAGE BREAK ===\n\n".join(
            f"PAGE {i+1}:\n{page}" for i, page in enumerate(pages[:2])
        )
        
        if len(full_text) > 10000:
            full_text = full_text[:10000] + "\n... [truncated]"
        
        # Check if this looks like a waiver email
        if "waive" not in full_text.lower() and "waiv" not in full_text.lower():
            return None
        
        prompt = f"""Extract waiver information if present. Return ONLY valid JSON with NO markdown.

Document: {doc_ref}

{full_text}

Extract:
{{
  "awb": "airway bill if specified or null",
  "month": "YYYY-MM if month specified or null",
  "charge_type": "what is waived",
  "sender": "sender name",
  "sender_email": "sender email",
  "conditions": "any conditions or null"
}}

Return null if not a waiver email."""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=1000
            )
            
            text = response.choices[0].message.content
            if text.strip().lower() == "null":
                return None
            
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(text)
            if data:
                data["_source_doc"] = doc_ref
                return data
            
            return None
            
        except Exception as e:
            print(f"Waiver extraction failed for {doc_ref}, using fallback: {e}", file=sys.stderr)
            return self.fallback.extract_waiver(doc_text, doc_ref, pages)
    
    def find_evidence_quote(self, pages: list[str], search_text: str, min_length: int = 12) -> dict | None:
        """Find a quote in pages that matches search text."""
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
