"""Your harness. The grader calls exactly these three commands, in a fresh process each time:

    python harness.py ingest <batch_dir> --state-dir <dir>
    python harness.py report --as-of YYYY-MM-DD [--mode supervised|autonomous] [--state-dir <dir>] > report.json
    python harness.py feedback <feedback.json> --state-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
import io

# Ensure stdout uses UTF-8 encoding on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
import sys
from pathlib import Path

# Import our modules
from state import State
from extractor import DocumentExtractor, ocr_scan

DEFAULT_STATE = ".state"


def ingest(batch_dir: str, state_dir: str) -> None:
    """Ingest batch directory into persistent state with extraction."""
    batch_path = Path(batch_dir)
    if not batch_path.is_dir():
        raise ValueError(f"Batch directory not found: {batch_dir}")
    
    state = State(state_dir)
    
    try:
        from claude_extractor import ClaudeExtractor
        claude = ClaudeExtractor()
        
        extractor = DocumentExtractor(batch_path)
        documents = extractor.extract_batch()
        
        for doc in documents:
            batch_name = doc["batch"]
            received_date = doc["received_date"] or "1970-01-01"
            
            state.add_document(
                batch=batch_name,
                file=doc["file"],
                received_date=received_date,
                content=doc["content"],
                doc_type=doc["doc_type"],
                is_scan=doc["is_scan"]
            )
            
            if doc["pages"]:
                state.add_document_pages(doc["file"], doc["pages"])
            
            for att in doc.get("attachments", []):
                att_ref = att["doc_ref"]
                att_name = att["name"].lower()
                
                state.add_document(
                    batch=batch_name,
                    file=att_ref,
                    received_date=received_date,
                    content=att["content"],
                    doc_type=att.get("ext"),
                    is_scan=att.get("is_scan", False)
                )
                
                if att["pages"]:
                    state.add_document_pages(att_ref, att["pages"])
                elif att.get("is_scan"):
                    ocr_pages = ocr_scan(att["content"])
                    if ocr_pages:
                        state.add_document_pages(att_ref, ocr_pages)
                
                pages = att.get("pages", [])
                # CRITICAL FIX: Removed "if not pages: continue" - extraction can work with empty pages
                
                # Invoice extraction
                # Check if this looks like an invoice (TX-*, CDU-*, CDI-*, TXI-*, or contains "invoice"/"inv")
                att_lower = att_name.lower()
                att_upper = att_name.upper()
                is_invoice = any([
                    "invoice" in att_lower,
                    "inv" in att_lower,
                    att_upper.startswith(("TX-", "CDU-", "CDI-", "TXI-"))
                ])
                
                if is_invoice:
                    invoice_data = claude.extract_invoice("", att_ref, pages)
                    if invoice_data:
                        invoice_id = invoice_data.get("invoice_id", att_name)
                        state.add_entity(
                            entity_id=f"invoice:{invoice_id}:{batch_name}",
                            entity_type="invoice",
                            data=invoice_data,
                            source_doc=att_ref,
                            batch=batch_name,
                            received_date=received_date
                        )
                
                # Contract extraction
                elif "msa" in att_name or "contract" in att_name or "amd" in att_name or "exp" in att_name:
                    contract_data = claude.extract_contract_summary("", att_ref, pages)
                    if contract_data:
                        contract_id = contract_data.get("contract_id", att_name)
                        # Make entity_id unique per source document
                        entity_key = f"{contract_id}:{att_ref}"
                        state.add_entity(
                            entity_id=f"contract:{entity_key}",
                            entity_type="contract",
                            data=contract_data,
                            source_doc=att_ref,
                            batch=batch_name,
                            received_date=received_date
                        )
                        
                        if contract_data.get("has_rate_table"):
                            rates = claude.extract_rate_table("", att_ref, pages, contract_id)
                            for i, rate in enumerate(rates or []):
                                state.add_entity(
                                    entity_id=f"rate:{contract_id}:{i}:{batch_name}",
                                    entity_type="rate",
                                    data=rate,
                                    source_doc=att_ref,
                                    batch=batch_name,
                                    received_date=received_date
                                )
                        
                        if contract_data.get("has_fuel_table"):
                            fuel_rates = claude.extract_fuel_surcharge_table("", att_ref, pages, contract_id)
                            for i, fuel in enumerate(fuel_rates or []):
                                state.add_entity(
                                    entity_id=f"fuel:{contract_id}:{fuel['month']}:{batch_name}",
                                    entity_type="fuel_surcharge",
                                    data=fuel,
                                    source_doc=att_ref,
                                    batch=batch_name,
                                    received_date=received_date
                                )
                
                # Tracking export extraction
                elif "track" in att_name or att.get("ext") == "xlsx":
                    events = claude.extract_tracking_export("", att_ref, pages)
                    for i, event in enumerate(events):
                        awb = event.get("awb", "")
                        state.add_entity(
                            entity_id=f"tracking:{awb}:{i}:{batch_name}",
                            entity_type="tracking",
                            data={
                                "awb": awb,
                                "pickup_date": event.get("event_date") if event.get("event") == "PICKED_UP" else None,
                                **event
                            },
                            source_doc=att_ref,
                            batch=batch_name,
                            received_date=received_date
                        )
                
                # Payment ledger extraction
                elif "register" in att_name or "ledger" in att_name or "ap-" in att_name:
                    entries = claude.extract_payment_ledger("", att_ref, pages)
                    for i, entry in enumerate(entries):
                        inv_id = entry.get("invoice_id", "")
                        state.add_entity(
                            entity_id=f"payment:{inv_id}:{i}:{batch_name}",
                            entity_type="payment_ledger",
                            data=entry,
                            source_doc=att_ref,
                            batch=batch_name,
                            received_date=received_date
                        )
            
            # Check if email is a waiver
            if doc["pages"]:
                waiver_data = claude.extract_waiver("", doc["file"], doc["pages"])
                if waiver_data:
                    waiver_id = f"{waiver_data.get('awb', 'month')}:{batch_name}"
                    state.add_entity(
                        entity_id=f"waiver:{waiver_id}",
                        entity_type="waiver",
                        data=waiver_data,
                        source_doc=doc["file"],
                        batch=batch_name,
                        received_date=received_date
                    )
        
        print(f"Ingested {len(documents)} documents from {batch_path.name}", file=sys.stderr)
    
    except Exception as e:
        print(f"Ingestion error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        state.close()


def report(as_of: str, mode: str, state_dir: str) -> dict:
    """Generate report for as_of date in specified mode."""
    state = State(state_dir)
    
    try:
        from business_rules import FindingsDetector
        
        detector = FindingsDetector(state)
        report_data = detector.detect_all_findings(as_of, mode)
        
        return report_data
    
    finally:
        state.close()


def feedback(feedback_file: str, state_dir: str) -> None:
    """Process feedback file and update state."""
    feedback_path = Path(feedback_file)
    if not feedback_path.is_file():
        raise ValueError(f"Feedback file not found: {feedback_file}")
    
    state = State(state_dir)
    
    try:
        feedback_data = json.loads(feedback_path.read_text())
        
        world = feedback_data.get("world", "W1")
        after_batch = feedback_data.get("after_batch")
        decided_at = feedback_data.get("decided_at")
        
        for item in feedback_data.get("items", []):
            fact_id = item.get("item_id")
            fact_type = item["fact"].get("type")
            scope = item.get("scope", {})
            
            state.add_feedback_fact(
                fact_id=fact_id,
                batch=after_batch,
                fact_type=fact_type,
                scope_kind=scope.get("kind", "one_off"),
                applies_to=scope.get("applies_to", {}),
                valid_from=scope.get("valid_from"),
                valid_to=scope.get("valid_to"),
                value=item["fact"].get("value", {}),
                decided_at=decided_at
            )
        
        print(f"Processed {len(feedback_data.get('items', []))} feedback items", file=sys.stderr)
    
    finally:
        state.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="harness.py", description="Freight invoice audit harness")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ingest", help="read one batch folder into the state dir")
    p.add_argument("batch_dir")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p = sub.add_parser("report", help="print report.json for a date")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD; only documents received by then count")
    p.add_argument("--mode", choices=["supervised", "autonomous"], default="supervised")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    p = sub.add_parser("feedback", help="take in a person's decisions (feedback.json)")
    p.add_argument("feedback_file")
    p.add_argument("--state-dir", default=DEFAULT_STATE)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "ingest":
            ingest(a.batch_dir, a.state_dir)
        elif a.cmd == "report":
            json.dump(report(a.as_of, a.mode, a.state_dir), sys.stdout, indent=1)
            sys.stdout.write("\n")
        else:
            feedback(a.feedback_file, a.state_dir)
    except Exception as e:
        print(f"harness.py {a.cmd}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())

