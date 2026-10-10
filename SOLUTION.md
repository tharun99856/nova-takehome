# My Solution

## How to Run It

**Prerequisites:**
```bash
# Create virtual environment and install dependencies
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r harness\requirements.txt
```

**Commands:**
```bash
# Run practice grader
python -m venv .venv
.venv\Scripts\python.exe grader\run_grader.py --harness ".venv\Scripts\python.exe harness\harness.py" --data data\scenarios --key data\scenarios\answers --mode supervised --out report_card.json

# Generate exam answer sheet  
.venv\Scripts\python.exe harness\harness.py ingest data\exam\batch_01 --state-dir .exam-state
.venv\Scripts\python.exe harness\harness.py ingest data\exam\batch_02 --state-dir .exam-state
.venv\Scripts\python.exe harness\harness.py report --as-of 2031-02-28 --mode supervised --state-dir .exam-state > out\exam_report.json
.venv\Scripts\python.exe grader\make_sheet.py out\exam_report.json -o answer_sheet.json
```

The harness implements all three required commands:
- `python harness\harness.py ingest <batch_dir> --state-dir <dir>`
- `python harness\harness.py report --as-of YYYY-MM-DD [--mode supervised|autonomous] --state-dir <dir>`
- `python harness\harness.py feedback <feedback.json> --state-dir <dir>`

## Architecture

### Core Components

1. **harness.py** - Main entry point, orchestrates ingestion, reporting, and feedback
2. **state.py** - SQLite-based persistence layer for documents and extracted entities
3. **extractor.py** - Document extraction using grader's extract.py utilities  
4. **fallback_extractor.py** - Deterministic regex-based extraction when Claude API unavailable
5. **claude_extractor.py** - LLM-based semantic extraction (requires ANTHROPIC_API_KEY)
6. **business_rules.py** - Detection logic for all six finding classes

### Data Flow

```
.eml files → extractor → state (SQLite) → business_rules → report.json
```

**Ingestion Pipeline:**
1. Read .eml files from batch directory
2. Extract email metadata (sender, date, subject)
3. Extract attachments (PDFs, Excel files)
4. Parse text from attachments using grader/extract.py
5. Extract structured entities:
   - Invoices (lines, amounts, dates, AWBs)
   - Contracts (parties, rates, rebate programs, expiry)
   - Rate tables (lanes, weight brackets, prices)
   - Fuel surcharge tables (monthly percentages)
   - Tracking exports (pickup dates, AWBs)
   - Payment ledgers (paid status, dates)
   - Waivers (AWB-specific charge waivers)
6. Store everything in SQLite with batch tracking

**Report Generation:**
1. Query entities up to as_of date
2. Run detection logic for each class:
   - **Overcharge**: Match invoice lines to contract rates, calculate differences
   - **Duplicate**: Find same AWB billed multiple times, check payment ledger
   - **Waived_but_billed**: Match waiver emails to invoice charges
   - **Late fees**: Check payment ledger against due dates
   - **Cashback**: Calculate quarterly spend, compare to rebate tiers
   - **Expiry**: Flag contracts ending within 60 days
3. Apply mode-specific actions (draft vs execute)
4. Output findings + portfolio (cashback, expiry, late_fee_risk)

### What Works

- Overcharge detection - Matches freight charges to contract rates, validates pickup dates
- Waived_but_billed - AWB-specific waivers matched to invoice charges
- Cashback - Quarterly spend calculation with tier matching
- Expiry - Contract end date alerts
- Feedback processing - Stores feedback and marks findings with learned_at
- Mode handling - Supervised (draft) vs autonomous (execute) actions
- Evidence tracking - Doc refs, page numbers, quotes for all findings

### What Doesn't Work

- **Duplicate detection incomplete** - Finds exact ID duplicates but misses semantic duplicates (same AWB, different invoice ID)
- **Late fee logic incomplete** - Detects late fee risk but doesn't validate late_fee_not_owed properly
- **Conflicts not detected** - Logic exists but needs tuning to compare conflicting sources
- **Cannot_determine not implemented** - Would need to track which documents are referenced but missing
- **Feedback not fully applied** - Stores feedback but doesn't use it to modify/supersede existing findings
- **Currency conversion missing** - INR amounts not properly converted to USD using contract rates
- **Confidence scoring static** - Uses fixed values (0.85-0.95) instead of calculating based on evidence quality

### The Eval Case That Caught a Bug

**Bug:** Contract extraction was overwriting when multiple contracts had the same ID

**The Case:** TBX-US-EXP-01 appeared in two documents - the main MSA without rebate info, and an amendment with rebate tiers. My initial `_build_contract_map` function would keep whichever came last, losing rebate data if the MSA came after the amendment.

**How I Found It:** Created debug_cashback.py to trace why cashback detection returned 0 findings despite calculating $4,050 in quarterly spend. Discovered the contract map only had `has_rebate_program: False`.

**The Fix:** Modified `_build_contract_map` to prefer more complete contracts:
```python
if cid in contract_map:
    existing = contract_map[cid]
    # Prefer one with rebate program info
    if data.get("has_rebate_program") and not existing.get("has_rebate_program"):
        contract_map[cid] = {...}
```

**Result:** Cashback detection now works, finding the $4,050.54 rebate for 2035-Q1.

### Known Limitations

1. **Practice score: ~30-40%** - Detection logic needs more refinement for edge cases
2. **Exam extraction** - Limited by fallback extractor's regex patterns (no Claude API key)
3. **Currency conversion** - INR to USD conversion not fully implemented
4. **Feedback application** - Stored but not fully applied to modify existing findings
5. **Confidence scores** - Fixed values, not dynamically calculated
6. **Windows compatibility** - Some paths need absolute references due to subprocess handling

### Time Spent

- Architecture & core extraction: 4 hours
- Detection logic (overcharge, cashback, expiry): 6 hours
- Debugging & Windows compatibility: 3 hours
- Documentation: 1 hour
- **Total: ~14 hours**

### What I Would Do Next

With more time, I would:

1. **Improve semantic duplicate detection** - Match by AWB + amount + date window
2. **Complete late fee logic** - Grace periods, fee rates from contracts
3. **Add conflict detection** - Compare tracking vs invoice dates/amounts
4. **Tune confidence scores** - Based on evidence completeness, source authority
5. **Add more contract extraction patterns** - Handle more document layouts
6. **Implement proper currency conversion** - Using contract exchange rates
7. **Apply feedback to modify findings** - Supersedes logic, learned_at propagation
8. **Add comprehensive logging** - For debugging in production
9. **Build custom eval set** - Test edge cases and corner scenarios
10. **Fix Windows subprocess issues** - Proper shell escaping for grader compatibility

