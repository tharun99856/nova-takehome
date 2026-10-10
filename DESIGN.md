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



## Fact Model

### Core Entities

The system extracts and stores these structured entities:

#### 1. Invoice
```python
{
  "invoice_id": str,           # Unique invoice identifier
  "invoice_date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD",
  "total_amount": str,         # Decimal string
  "currency": "USD" | "INR",
  "supplier": str,             # Carrier name
  "customer": str,
  "contract_ref": str,         # Referenced contract ID
  "lines": [InvoiceLine]       # Line items
}
```

#### 2. InvoiceLine
```python
{
  "line_num": int,
  "awb": str,                  # Airway bill number
  "ship_date": "YYYY-MM-DD",
  "pickup_date": "YYYY-MM-DD",
  "origin": str,               # 3-letter code
  "destination": str,          # 3-letter code
  "weight_kg": str,
  "pieces": int,
  "charge_type": str,          # "Air freight", "Fuel surcharge", etc.
  "rate": str,
  "amount": str,
  "description": str
}
```

#### 3. Contract
```python
{
  "contract_id": str,
  "parties": [{"name": str, "role": "carrier" | "customer"}],
  "effective_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "contract_type": "MSA" | "Amendment",
  "amends_contract": str,      # Parent contract if amendment
  "schedule1_contacts": [Contact],
  "has_rate_table": bool,
  "has_fuel_table": bool,
  "has_rebate_program": bool,
  "rebate_tiers": [RebateTier]
}
```

#### 4. Contact (Schedule 1)
```python
{
  "person": str,
  "role": str,                 # Job title
  "categories": [str],         # ["rates", "waivers", "payment_terms", etc.]
  "email": str
}
```

#### 5. Waiver
```python
{
  "awb": str | null,           # Specific shipment or null for general
  "month": "YYYY-MM" | null,   # Monthly waiver
  "charge_type": str,          # What is waived
  "sender": str,
  "sender_email": str,
  "conditions": str | null
}
```

#### 6. Rate
```python
{
  "lane": str,                 # "USE2-INW2"
  "weight_min": str,
  "weight_max": str,
  "rate": str,                 # Per kg
  "currency": "USD" | "INR",
  "effective_from": "YYYY-MM-DD",
  "effective_to": "YYYY-MM-DD",
  "contract_id": str
}
```

#### 7. TrackingEvent
```python
{
  "awb": str,
  "event": "PICKED_UP" | "DELIVERED",
  "event_date": "YYYY-MM-DD",
  "location": str
}
```

### Relationships

```
Contract 1──→ N Rates
Contract 1──→ N RebateTiers
Contract 1──→ N Schedule1Contacts
Contract 1──→ 0..1 AmendedContract (parent)

Invoice 1──→ N InvoiceLines
Invoice N──→ 1 Contract (via contract_ref)

InvoiceLine N──→ 1 TrackingEvent (via AWB)
InvoiceLine N──→ 0..1 Waiver (via AWB + charge_type)
InvoiceLine N──→ 0..1 Rate (via lane + weight + date)
```

### Facts vs. Findings

**Facts**: Extracted entities (invoices, contracts, waivers) - stored in SQLite  
**Findings**: Detected issues derived from facts - generated per report, not stored

This separation allows:
- Reprocessing findings as rules improve
- Learning from feedback without reingesting
- Temporal queries ("as of" date filtering)

## People in the Loop

### Authority Model

The system validates authority for actions based on Schedule 1 contacts:

```python
AUTHORITY_CATEGORIES = {
    "rates": ["rate changes", "overcharge disputes"],
    "waivers": ["waive charges", "fee forgiveness"],
    "payment_terms": ["due date changes", "late fee disputes"],
    "notices": ["contract renewals", "termination notices"],
    "billing_disputes": ["invoice disputes", "duplicate claims"]
}
```

### Human Decision Points

1. **Waiver Validation**
   - Check: Is sender in Schedule 1?
   - Check: Does sender have "waivers" authority?
   - Action: Accept if yes, escalate if no

2. **High-Value Disputes** (>$5,000)
   - Always escalate to human review
   - Action: draft:dispute → human approval required

3. **Conflicts**
   - Two trusted sources disagree (e.g., contract says X, email says Y)
   - Action: Present both sources, ask human to decide

4. **Missing Documents**
   - Cannot determine answer without document
   - Action: Ask who holds it (based on Schedule 1 roles)

### Feedback Loop

```
Human reviews finding → accepts/rejects/updates → feedback.json
                           ↓
Harness ingests feedback → updates entity confidence
                           ↓
Future reports apply learned corrections
```

**Feedback Types**:
- `accept`: Confirms finding is correct (increases confidence)
- `reject`: False positive (mark entity as verified clean)
- `update_amount`: Correct calculation error (adjust entity data)
- `add_missing`: Human found something we missed (add new entity)

## New Documents

### Incremental Batch Processing

The system handles new batches incrementally:

1. **Ingest Phase**
   ```
   batch_02 arrives → extract entities → check for duplicates → store
   ```
   
2. **Conflict Detection**
   ```
   New contract amends old contract → compare terms → flag conflicts
   New invoice references old waiver → re-evaluate waiver applicability
   ```

3. **Temporal Queries**
   ```
   Report --as-of 2035-06-01 → filter entities by received_date ≤ 2035-06-01
   ```

### Document Types and Handling

| Document Type | Recognition Pattern | Extraction Method | Impact on Findings |
|--------------|---------------------|-------------------|-------------------|
| Invoice PDF | Filename: `TX-*`, `CDU-*`, `CDI-*` | Regex + LLM fallback | Direct - creates findings |
| Contract PDF | Filename: `MSA-*`, `*-AMD-*` | Regex for metadata, LLM for clauses | Indirect - provides rates/rules |
| Waiver Email | Subject/body: "waive", "waiver" | Email parser + pattern matching | Direct - prevents findings |
| Tracking Excel | `.xlsx` with AWB columns | Excel reader + row parser | Indirect - validates pickup dates |
| Payment Ledger | `.xlsx` with invoice_id, paid_date | Excel reader + row parser | Indirect - affects late fees |

### Amendment Handling

**Scenario**: New amendment arrives that changes rates retroactively

**Process**:
1. Extract amendment contract
2. Identify parent contract via `amends_contract` field
3. Update rate entities with new effective dates
4. Re-run detection logic for affected invoices
5. If findings change, mark as superseded in report

**Example**:
```
batch_01: Invoice uses $5/kg rate → Finding: overcharge $100
batch_02: Amendment effective backdated, new rate $6/kg → Retract finding
```

### Handling Document Arrival Order

**Design Principle**: Findings are deterministic based on documents available, regardless of order.

**Implementation**:
- Entity deduplication by (type, id, source_doc)
- Rate selection uses effective_date, not received_date
- Waivers apply based on email date, not batch order
- Conflicts arise only when sources disagree, not from order

**Test Case**: Waiver arrives before invoice
```
batch_01: Waiver for June delivery fees
batch_02: June invoice with delivery fee → Finding: waived_but_billed ✓
```

**Test Case**: Invoice arrives before waiver
```
batch_01: June invoice with delivery fee → No finding yet
batch_02: Waiver for June delivery fees → Re-evaluate → Finding: waived_but_billed ✓
```

## What I'd Do Next

### 1. Rate Table Extraction (Highest Priority)
**Impact**: Enables overcharge detection (~30% of potential findings)

**Approach**:
```python
# Use tabula-py for structured table extraction
import tabula

def extract_rate_table_from_pdf(pdf_path):
    # Extract all tables from PDF
    tables = tabula.read_pdf(pdf_path, pages='all', multiple_tables=True)
    
    for table in tables:
        # Identify rate table by column headers
        if 'Lane' in table.columns and 'Rate' in table.columns:
            for row in table.iterrows():
                yield {
                    'lane': row['Lane'],
                    'weight_min': row['Weight Min'],
                    'weight_max': row['Weight Max'],
                    'rate': row['Rate'],
                    'currency': row['Currency']
                }
```

**Estimated Time**: 4-6 hours
- 2 hours: Tabula integration and testing
- 2 hours: Pattern matching for various table formats
- 2 hours: Edge case handling and validation

### 2. Rebate Tier Extraction (High Priority)
**Impact**: Better cashback detection coverage

**Approach**:
- Multi-pattern extraction (tables + narrative text)
- Fallback chain: tabula → regex → LLM
- Confidence scoring per tier based on extraction method

**Estimated Time**: 2-3 hours

### 3. Conflict Detection (Medium Priority)
**Impact**: Handle contradictory sources gracefully

**Design**:
```python
class ConflictDetector:
    def check_rate_conflict(self, invoice_line, contract_rate, email_rate):
        if contract_rate != email_rate:
            return {
                "class": "conflict",
                "sources": [
                    {"doc": contract_doc, "value": contract_rate},
                    {"doc": email_doc, "value": email_rate}
                ],
                "action": "human_review"
            }
```

**Estimated Time**: 3-4 hours

### 4. Payment Ledger Integration (Medium Priority)
**Impact**: Enable late fee detection

**Approach**:
- Enhanced date extraction patterns for varied formats
- Payment matching by invoice_id across ledgers
- Grace period calculation per contract terms

**Estimated Time**: 2-3 hours

### 5. Performance Optimization (Lower Priority)
**Impact**: 2-3x faster ingestion

**Approaches**:
- Parallel PDF extraction with ThreadPoolExecutor
- Streaming PDF reading (don't load full file into memory)
- SQLite connection pooling
- Batch insert optimization

**Estimated Time**: 3-4 hours

### 6. Test Coverage Expansion (Important but Lower Priority)
**Impact**: Catch regressions earlier

**Additions Needed**:
- Unit tests for extraction patterns (pytest)
- Integration tests for full pipeline
- Property-based testing for edge cases (hypothesis)
- Expand eval cases to 50+ scenarios

**Estimated Time**: 6-8 hours

### 7. Advanced Features

**Semantic Duplicate Detection**:
- Use string similarity (Levenshtein distance) for AWB matching
- Cluster similar amounts within threshold
- Time-window based grouping (same charge within 90 days)

**Multi-Modal Evidence**:
- Include screenshots/images as evidence
- OCR confidence scoring
- Visual highlighting of key fields

**Adaptive Confidence Scoring**:
- Track precision/recall per finding class
- Adjust confidence thresholds based on feedback
- Bayesian updating with human corrections

**Estimated Time**: 12-15 hours for all advanced features

---

## Architecture Diagrams

### Data Flow
```
┌─────────────────────────────────────────────────────────────┐
│                     INGESTION PHASE                          │
├─────────────────────────────────────────────────────────────┤
│  .eml files  →  Email Parser  →  PDF Extractor             │
│                                  │                           │
│                                  ↓                           │
│                           Text Pages (per page)             │
│                                  │                           │
│                                  ↓                           │
│                    ┌─────────────────────────┐              │
│                    │   Entity Extractor      │              │
│                    │  (Claude or Fallback)   │              │
│                    └─────────────────────────┘              │
│                                  │                           │
│                                  ↓                           │
│              ┌──────────────────────────────────┐           │
│              │  Structured Entities (JSON)      │           │
│              │  - Invoices + Lines              │           │
│              │  - Contracts + Rates             │           │
│              │  - Waivers                       │           │
│              │  - Tracking Events               │           │
│              └──────────────────────────────────┘           │
│                                  │                           │
│                                  ↓                           │
│                          SQLite Database                     │
│                      (entities + document_pages)            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      DETECTION PHASE                         │
├─────────────────────────────────────────────────────────────┤
│  SQLite Entities  →  Business Rules Engine                  │
│                           │                                  │
│                           ├→ Overcharge Detector             │
│                           ├→ Duplicate Detector              │
│                           ├→ Waiver Matcher                  │
│                           ├→ Late Fee Calculator             │
│                           ├→ Cashback Calculator             │
│                           └→ Expiry Monitor                  │
│                                  │                           │
│                                  ↓                           │
│                         Findings (with evidence)            │
│                                  │                           │
│                                  ├→ Apply Mode Rules         │
│                                  │  (supervised/autonomous)  │
│                                  │                           │
│                                  ├→ Score Confidence         │
│                                  │                           │
│                                  ↓                           │
│                          report.json                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      FEEDBACK PHASE                          │
├─────────────────────────────────────────────────────────────┤
│  feedback.json  →  Parse Corrections                        │
│                           │                                  │
│                           ├→ Update Entity Confidence        │
│                           ├→ Store Learned Facts             │
│                           └→ Mark Verified Clean             │
│                                  │                           │
│                                  ↓                           │
│                      SQLite (feedback_facts)                │
│                                  │                           │
│         (Applied in next report generation)                 │
└─────────────────────────────────────────────────────────────┘
```

### State Schema
```sql
-- Core entities table
CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    data TEXT NOT NULL,  -- JSON blob
    source_doc TEXT NOT NULL,
    batch TEXT NOT NULL,
    received_date TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Document pages for evidence lookup
CREATE TABLE document_pages (
    doc_ref TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    page_text TEXT NOT NULL,
    PRIMARY KEY (doc_ref, page_num)
);

-- Feedback storage
CREATE TABLE feedback_facts (
    finding_id TEXT NOT NULL,
    verdict TEXT NOT NULL,  -- accept, reject, update_amount
    updated_data TEXT,  -- JSON of corrections
    learned_at TEXT NOT NULL,
    PRIMARY KEY (finding_id, learned_at)
);

-- Indexes for performance
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_batch ON entities(batch);
CREATE INDEX idx_entities_received ON entities(received_date);
```

---

## Lessons Learned

### What Worked Well

1. **SQLite for State**
   - Simple, reliable, no setup overhead
   - Easy debugging (can inspect with sqlite3 CLI)
   - Good performance for our data size

2. **Dual Extraction Strategy**
   - Fallback made development possible without API credits
   - Regex patterns are fast and deterministic
   - LLM would improve accuracy but isn't critical

3. **Entity-Centric Design**
   - Clean separation between extraction and detection
   - Easy to add new finding types
   - Business rules operate on typed data

4. **Evidence-First Approach**
   - Storing page references from day 1 saved time
   - Grader quote validation caught extraction bugs early

### What I'd Change

1. **Start with Rate Table Extraction**
   - Overcharge is ~30% of findings
   - Should have tackled this first, not last
   - Would have used tabula-py from the start

2. **More Structured Testing**
   - Should have created 50+ eval cases upfront
   - Property-based testing would catch edge cases
   - Spent too much time on manual debugging

3. **Pattern Library Earlier**
   - Ended up with scattered regex patterns
   - Should have created centralized pattern registry
   - Would make updates easier

4. **Windows Compatibility**
   - Subprocess issues cost hours of debugging
   - Should have developed on Linux or used WSL
   - Cross-platform testing needed earlier

### Key Insights

1. **Real-world data is messy**
   - Multiple invoice formats within same carrier
   - Date formats vary (YYYY-MM-DD vs DD/MM/YYYY)
   - Contract language is inconsistent
   - → Need flexible extraction with confidence scoring

2. **Evidence quality matters more than detection logic**
   - Can detect a finding but fail grading if evidence is wrong
   - Page references must be exact
   - Quotes must match byte-for-byte
   - → Invest in extraction quality, not just detection

3. **Feedback is the hardest part**
   - Easy to store feedback
   - Hard to apply it correctly to exactly the right cases
   - Requires understanding intent, not just pattern matching
   - → Would need more time to get this fully right

4. **Time allocation was backwards**
   - Spent 60% on infrastructure, 40% on detection
   - Should have been 30% infrastructure, 70% detection
   - Rate tables should have been day 1, not day 15
   - → Start with highest-impact features first
