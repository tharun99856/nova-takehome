# Design Document

## System Overview

The harness is built as a three-phase pipeline: **Ingest → Store → Detect**. Each phase is designed to be stateless and reproducible, with all state managed in a SQLite database.

## Design Decisions

### 1. SQLite for State Management

**Why:** Simple, portable, ACID-compliant, no external dependencies
**How:** Single file database with tables for documents, entities, and feedback
**Tables:**
- `documents`: Raw email and attachment content, indexed by batch
- `document_pages`: Extracted text per page for evidence quoting
- `entities`: Structured data (invoices, contracts, rates) as JSON blobs
- `feedback_facts`: User corrections and learned rules

**Benefits:**
- Easy to reset state (delete .db file)
- Query by date ranges for batch processing
- Portable across runs

### 2. Dual Extraction Strategy

**Fallback (regex-based):**
- Fast, deterministic
- Works offline
- Limited to structured patterns
- Used when no API key available

**Claude (LLM-based):**
- Handles varied layouts
- Semantic understanding
- Requires API costs
- Better for complex documents

**Strategy:** Try Claude first, fallback on error or unavailability

### 3. Entity-Centric Detection

Instead of operating directly on raw documents, we extract structured entities first:
- Invoice → lines with AWB, charge type, amount
- Contract → rates, tiers, contacts, dates
- Tracking → pickup dates per AWB

This separation allows business rules to operate on clean, typed data without re-parsing documents.

### 4. Evidence-First Architecture

Every finding must cite:
- Source document (batch/file#attachment)
- Page number
- Exact quote (for grader validation)

Evidence is captured during detection, not reconstructed later.

### 5. Deterministic Rate Matching

Overcharge detection follows a strict precedence:
1. Find pickup date (tracking → line → invoice date)
2. Find applicable rate (contract, lane, weight bracket, effective date)
3. Calculate correct amount
4. Compare to billed amount

This ensures reproducibility and debuggability.

### 6. Quarterly Cashback Aggregation

Cashback detection groups invoices by contract and calendar quarter:
- Sum qualifying spend (freight + fuel + surcharges, minus exclusions)
- Find highest tier reached
- Calculate owed rebate (tier % × total QS)
- Subtract credits already received

### 7. Mode-Specific Actions

**Supervised mode:** All outbound actions are drafted (draft:dispute, draft:claim_credit)
**Autonomous mode:** Safe actions are executed automatically if they pass unattended-action test:
- Evidence complete
- No conflicts
- Under $5,000
- Reversible action

## Trade-offs Made

### Chose: Simple regex extraction over full OCR pipeline
**Why:** Time constraint, most documents have text layers
**Cost:** May miss scanned documents without text
**Mitigation:** Added rapidocr as fallback for image-only PDFs

### Chose: Fixed confidence scores over ML-based calibration
**Why:** No training data, no time to build confidence model
**Cost:** Scores don't reflect actual uncertainty
**Mitigation:** Set conservative defaults (0.85-0.90)

### Chose: In-memory rate lookups over SQL indexes
**Why:** Small dataset (< 100 rates), simpler code
**Cost:** Would not scale to thousands of contracts
**Mitigation:** Could add SQL indexes if needed

### Chose: Batch ingestion over streaming
**Why:** Grader expects batch-by-batch processing
**Cost:** Can't process individual emails in real-time
**Mitigation:** Design allows streaming in future (just change ingestion loop)

## What I Learned

1. **Document extraction is 60% of the work** - Getting clean, structured data from PDFs is harder than the business logic

2. **Evidence quoting is critical** - The grader needs exact quotes, so maintaining page-level text throughout is essential

3. **Windows path handling is painful** - Subprocess calls with paths need careful escaping, especially with backslashes

4. **Contracts have versions** - Same ID can appear in multiple documents (MSA, amendments), need to merge intelligently

5. **Quarterly calculations need careful date handling** - Invoice date determines quarter, but pickup date determines rate

## Architecture Diagram

```
+-----------------+
|   .eml files    |
|   (batch_NN/)   |
+--------+--------+
         |
         v
+-----------------+
|   extractor.py  | <- Uses grader/extract.py
|  + fallback/    | <- Regex patterns
|  + claude       | <- LLM (if API key)
+--------+--------+
         |
         v
+-----------------+
|   state.py      |
|   (SQLite DB)   |
|                 |
| - documents     |
| - entities      |
| - feedback      |
+--------+--------+
         |
         v
+-----------------+
| business_rules  |
|      .py        |
|                 |
| - overcharge    |
| - duplicate     |
| - waived        |
| - late fees     |
| - cashback      |
| - expiry        |
+--------+--------+
         |
         v
+-----------------+
|  report.json    |
|                 |
| - findings[]    |
| - portfolio{}   |
+-----------------+
```

## Testing Strategy

1. **Example cases** - Start with data/examples/, verify exact match
2. **Practice grader** - Iterate until green
3. **Custom eval set** - Build own edge cases (would do with more time)
4. **Exam mailbox** - Final validation on unseen data

## Scalability Considerations

**Current design handles:**
- ~100 documents per batch
- ~50 contracts
- ~1000 invoice lines

**To scale to production:**
- Add database indexes on entity_type, batch, received_date
- Use connection pooling for concurrent requests
- Cache contract rate lookups
- Parallelize batch ingestion
- Stream large documents instead of loading into memory

## Security Considerations

**Handled:**
- No code execution from documents
- SQL injection prevented (parameterized queries)
- Quotes from documents are escaped for JSON

**Would add:**
- Input validation on all external data
- Rate limiting on API calls
- Audit logging of all state changes
- Encryption of sensitive contract data



## Fact Model

The system maintains several types of facts in its state database:

### Extracted Facts (from documents)
- **Invoices**: invoice_id, supplier, total_amount, invoice_date, due_date, lines[]
- **Invoice Lines**: awb, charge_type, amount, weight_kg, origin, destination, pickup_date
- **Contracts**: contract_id, parties, effective_date, end_date, has_rebate_program, rebate_tiers[]
- **Rates**: contract_id, lane, weight_min, weight_max, rate, effective_from, effective_to
- **Fuel Surcharges**: contract_id, month, percentage
- **Tracking Events**: awb, event, event_date, pickup_date
- **Payment Ledger**: invoice_id, status, paid_date
- **Waivers**: awb, charge_type, sender, sender_email, scope

### Derived Facts (from business rules)
- **Findings**: class, invoice_id, verdict, amount_usd, evidence[], confidence
- **Portfolio Items**: cashback owed, expiry alerts, late fee risks

### Learned Facts (from feedback)
- **Feedback Facts**: fact_id, fact_type, scope (one-off, permanent, applies_to), valid_from, valid_to, value

All facts are timestamped by batch and can be queried "as of" any date, enabling temporal queries.

## Conflicts

**Definition:** A conflict occurs when two trusted sources provide incompatible information about the same fact.

**Examples:**
- Tracking export shows pickup date 2035-04-10, but invoice line shows 2035-04-12
- AWB document shows 363kg total, but invoice bills 483kg across multiple house bills
- Contract shows rate $4.71/kg, but email from authorized person announces $5.03/kg effective same date

**Handling:**
1. Detect conflicts by comparing amounts/dates from different source types
2. Calculate amount_range showing min/max possible impact
3. Set verdict="conflict" and include evidence from both sources
4. Action is always "human_review" - never automated
5. Store both source documents in evidence[]

**Not Implemented:** Conflict detection logic exists but needs source comparison tuning.

## Confidence

**Formula:** Each finding gets confidence score 0.0-1.0 based on:

1. **Evidence Completeness (40%)**: Do we have all documents needed?
   - All documents present: 1.0
   - Missing non-critical document: 0.8
   - Missing critical document: 0.5

2. **Source Authority (30%)**: Who says it?
   - Signed contract/amendment: 1.0
   - Email from Schedule 1 contact: 0.9
   - Email from carrier but not authorized: 0.7
   - Forwarded/quoted text: 0.6

3. **Extraction Quality (20%)**: How clean is the data?
   - Structured text extraction: 1.0
   - OCR with high confidence: 0.8
   - OCR with low confidence: 0.6

4. **Cross-Source Agreement (10%)**: Do sources agree?
   - All sources agree: 1.0
   - Minor discrepancies: 0.9
   - Significant discrepancies: 0.7

**Current Implementation:** Uses fixed scores (0.85-0.95) as placeholder. Would calculate dynamically with more time.

**Calibration:** Should validate on eval set that wrong items have lower confidence than correct items (measured by AUROC).

## People in the Loop

**Escalation Points:**
1. **Conflicts** - Always escalated with both sources
2. **High-value findings** - Over $5,000 in any finding class
3. **Missing documents** - Cannot_determine verdict with document name and holder
4. **Autonomous safety checks** - Findings that don't pass unattended-action test

**Human Actions:**
- Review drafted dispute emails before sending
- Approve credit claims before submission
- Resolve conflicts by choosing trusted source
- Provide missing documents or confirm they don't exist
- Give feedback on incorrect findings

**Feedback Loop:**
- Human corrections stored as feedback facts
- Applied to future batches via learned_at timestamps
- Scope determines if correction is one-off or permanent
- Supersedes mechanism allows corrections to replace findings

## Feedback

**Structure:**
```json
{
  "world": "W1",
  "after_batch": "batch_01",
  "decided_at": "2035-06-01",
  "items": [
    {
      "item_id": "overcharge:TX-US-2035-0256",
      "fact": {
        "type": "rate_override",
        "value": {"lane": "USC3-INS1", "rate": "5.03", "effective_from": "2035-04-01"}
      },
      "scope": {
        "kind": "applies_to",
        "applies_to": {"lane": "USC3-INS1", "from_date": "2035-04-01"}
      }
    }
  ]
}
```

**Application:**
1. Parse feedback file
2. Store facts in feedback_facts table
3. When detecting findings, check for applicable feedback
4. If feedback applies (by scope), modify finding or mark as learned
5. Add learned_at timestamp to show human input

**Scopes:**
- **one_off**: Applies only to the specific invoice/shipment
- **permanent**: Applies to all future cases
- **applies_to**: Applies to cases matching criteria (lane, date range, etc.)

**Current State:** Feedback is stored but not fully applied during detection. Would need to integrate feedback checks into each detection function.

## New Documents

**Adaptation Strategy:**

When new documents arrive in later batches:
1. **Amendments override contracts** - Latest effective rate wins
2. **Waivers are time-bound** - Check if waiver was one-off or permanent
3. **Payment updates change status** - Paid invoices can't be duplicates
4. **Tracking data completes picture** - Pickup dates refine overcharge detection

**Retroactive Changes:**
- Mark findings with retro=true if they change due to later document
- Use supersedes[] to link new finding to old one
- Keep both in report for audit trail

**Example:** Invoice shows $500 overcharge in batch_01. Amendment arrives in batch_02 showing rate increase was authorized. batch_02 report marks original finding as superseded.

**Implementation:** Detection runs fresh each batch with all data up to as_of date. Findings can appear, disappear, or change amounts as new data arrives.

## Cost

**Operational Costs:**

1. **Claude API (if used)**:
   - ~$0.003 per document page for extraction
   - ~40 documents/batch × 3 pages avg = $0.36/batch
   - 4 batches/quarter = $1.44/quarter
   - Negligible compared to money saved

2. **Storage**:
   - SQLite database grows ~50MB per quarter
   - Could archive old batches after 1 year
   - Total: ~200MB/year storage

3. **Compute**:
   - Ingestion: ~30 seconds per batch
   - Report generation: ~2 seconds
   - Could run on modest VM ($20/month)

**Savings:**
- Practice data shows $14,140 at stake across 22 findings
- Even 50% detection rate = $7,000/quarter saved
- ROI: 1000x in first quarter

**Scaling:**
- Current design handles 100 docs/batch easily
- With DB indexing, could scale to 1000 docs/batch
- Parallel processing could handle 10,000 docs/batch

## What I'd Do Next

**Priority 1 - Complete Core Detection:**
1. Implement semantic duplicate detection (AWB + amount fuzzy matching)
2. Add proper conflict detection (compare tracking vs invoice)
3. Complete late_fee_not_owed logic (check grace periods)
4. Implement cannot_determine (track document references)

**Priority 2 - Apply Feedback:**
1. Integrate feedback checks into each detection function
2. Implement supersedes logic properly
3. Add learned_at propagation
4. Build feedback application tests

**Priority 3 - Improve Quality:**
1. Calculate dynamic confidence scores
2. Add currency conversion using contract rates
3. Improve extraction patterns for more layouts
4. Handle scanned documents with OCR/vision

**Priority 4 - Production Readiness:**
1. Add comprehensive logging
2. Build monitoring dashboard
3. Add retry logic for API failures
4. Implement proper error handling
5. Add performance metrics

**Priority 5 - Testing:**
1. Build comprehensive eval set (50+ cases)
2. Test all edge cases from GLOSSARY.md
3. Add unit tests for each detection function
4. Test with different document layouts
5. Validate confidence calibration

**Priority 6 - User Experience:**
1. Build web UI for reviewing findings
2. Add bulk approval workflow
3. Generate dispute email templates
4. Add explanation generation for findings
5. Build audit trail viewer

