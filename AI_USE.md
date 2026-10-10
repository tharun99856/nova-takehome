# AI Tools Used

## Development Summary

**Total Time**: ~24 hours over 48-hour window  
**Primary AI Tool**: Kiro IDE with Claude Sonnet 4.5  
**Code Generation**: ~70% AI-generated, ~30% human-modified  
**Approach**: Iterative development with continuous AI collaboration

### Time Breakdown
- **Architecture & Core Pipeline**: 8 hours (Kiro collaboration)
- **Business Rules Implementation**: 10 hours (AI-assisted, human-validated)
- **Critical Bug Fix**: 2 hours (AI debugging assistance)
- **Documentation & Testing**: 4 hours (AI structure, human content)

### Effectiveness Assessment
- ✅ **Excellent**: Code generation, pattern matching, debugging assistance
- ✅ **Good**: Architecture design, documentation structure
- ⚠️ **Moderate**: Business logic edge cases (required human validation)
- ⚠️ **Needs Iteration**: Initial extraction patterns (required 3-4 refinements)

---

## Primary Tool: Kiro IDE (Claude Sonnet 4.5)

**Used for:** Architecture design, code generation, debugging, pattern refinement, test case analysis

**Time spent:** ~20 hours of AI collaboration out of 24 total hours

**Workflow:**
1. Started by reading BRIEF.pdf, GLOSSARY.md, and example cases
2. Asked Kiro to analyze the problem structure and propose architecture
3. Generated initial harness.py skeleton with command structure
4. Iteratively built each module (state.py, extractor.py, business_rules.py)
5. Debugged Windows compatibility issues with Kiro's help
6. Used Kiro to analyze grader output and fix detection logic

**Prompt Examples:**

"Read the BRIEF.pdf and GLOSSARY.md files. Design a harness architecture that can detect all six finding classes while maintaining evidence for grader validation."

"The grader is failing with 'No module named pymupdf'. Debug this Windows subprocess issue and suggest fixes."

"Analyze why cashback detection is returning 0 findings when my debug script shows $4,050 in quarterly spend. Check the business_rules.py logic."

"Generate a fallback extractor that uses regex patterns to extract contract rebate tiers from text like 'QS >= USD 55,000.00: 5%'."

**Code Generated vs Modified:**
- Kiro generated: ~70% (initial structure, boilerplate, extraction patterns)
- I modified: ~30% (business logic tuning, Windows fixes, debugging)

**Effectiveness:**
- Saved ~20 hours on boilerplate and document parsing
- Excellent at suggesting architecture patterns
- Very helpful for debugging cryptic errors
- Sometimes suggested Linux commands (needed Windows translation)
- Occasionally repeated failed approaches (needed explicit redirection)

## Claude API (via anthropic SDK)

**Used for:** Document extraction when ANTHROPIC_API_KEY is set

**Approach:**
- Send first 5 pages of contract/invoice to Claude
- Ask for structured JSON extraction
- Parse response into entity dictionaries

**Prompt Pattern:**
```
Extract invoice information. Return ONLY valid JSON with NO markdown.

Document: 0001.eml#TX-US-2035-0204.pdf

[PAGE 1 TEXT HERE]

Extract:
{
  "invoice_id": "...",
  "invoice_date": "YYYY-MM-DD",
  "lines": [
    {
      "awb": "...",
      "charge_type": "...",
      "amount": "...",
      ...
    }
  ]
}
```

**Result:** Worked well for structured extraction, but I didn't have time to fully integrate with proper error handling.

## GitHub Copilot

**Used for:** Inline code completion while implementing business logic

**Most Helpful:**
- Completing SQL queries
- Suggesting regex patterns for date/amount extraction
- Auto-completing repetitive boilerplate

**Less Helpful:**
- Sometimes suggested incorrect date parsing logic
- Didn't understand domain-specific terms from GLOSSARY.md

## Tools Summary

1. **Kiro IDE (Claude Sonnet 4.5)** - Primary development assistant (12 hours)
2. **Claude API (via anthropic SDK)** - Document extraction when API key available
3. **GitHub Copilot** - Inline code completion (2 hours)
4. **Manual debugging** - Python debugger, print statements, custom debug scripts

**Total AI-assisted time:** ~14 hours
**Estimated time without AI:** ~35-40 hours
**Time saved:** ~24 hours (63% faster)

**Key Insight:** AI is excellent for structure and boilerplate but requires human verification for business logic correctness. The combination of AI speed and human domain understanding is ideal.

## Lessons Learned

**AI Strengths:**
- Rapid prototyping and iteration
- Generating boilerplate and structure
- Explaining complex error messages
- Suggesting multiple approaches to problems

**AI Weaknesses:**
- Doesn't deeply understand domain requirements (had to correct cashback calculation logic several times)
- Can get stuck repeating failed approaches
- Sometimes over-engineers solutions (suggested ML models when regex would work)
- Doesn't catch logical errors in business rules (I had to verify against examples)

**Best Practices I Developed:**
1. Start with clear requirements and constraints
2. Break large problems into small, verifiable pieces
3. Always test AI-generated code against examples
4. Use AI for structure, verify logic manually
5. Keep prompts focused and specific
6. Redirect explicitly when AI repeats mistakes

## Time Breakdown

- With AI: ~14 hours total
- Estimated without AI: ~30-40 hours

**Where AI saved most time:**
- Document parsing infrastructure: 8 hours saved
- Boilerplate code generation: 4 hours saved
- Debugging cryptic errors: 3 hours saved
- Architecture brainstorming: 2 hours saved

**Where I still spent significant time:**
- Understanding domain requirements: 3 hours
- Debugging business logic: 4 hours
- Windows compatibility fixes: 3 hours
- Testing and validation: 2 hours
- Documentation: 1 hour

## Ethical Considerations

All code generated by AI was:
1. Reviewed and understood by me
2. Tested against provided examples
3. Modified to fit actual requirements
4. Documented with clear attribution

I take full responsibility for the final implementation, including any bugs or incorrect logic.



## Final Submission Notes (2026-10-10)

### GROQ API Integration Attempt
- Added support for GROQ API as LLM extraction provider (fallback to regex when API unavailable)
- API key provided but GROQ models (llama-3.3-70b-specdec, llama-3.1-70b-versatile) were decommissioned
- System gracefully falls back to regex-based extraction when API calls fail
- Code: `harness/claude_extractor.py`

### Known Issue: PDF Extraction in Exam Data
During final testing, discovered that PDF attachments in exam data batch are not being extracted properly:
- **Symptom**: 0 invoice entities in .exam-state despite 41 email documents ingested
- **Root Cause**: pymupdf import failing inside grader/extract.py during batch ingestion
- **Investigation**: Direct Python tests show pymupdf is installed and working, but subprocess/environment context during ingestion causes "No module named 'pymupdf'" errors
- **Impact**: Exam report contains only findings from non-invoice entities (2 waivers, 245 tracking events, 3 contracts) → expiry alerts but no overcharge/duplicate/waived findings
- **Time Constraint**: With < 1 hour to submission, insufficient time to fully debug Windows subprocess environment issue

### What Works
- Core harness architecture is solid
- Practice data ingests correctly and detects 6+ findings
- All 6 detection classes are implemented
- Documentation is complete
- Grader integration framework is in place

### Recommendations for Production
1. Investigate Windows subprocess Python environment initialization
2. Add explicit pymupdf installation verification step before batch processing
3. Consider bundling grader utilities into harness package to avoid sys.path.insert complications
4. Add unit tests for PDF extraction before batch ingestion



## Critical Bug Fix - Invoice Extraction (Final Hour)

### Problem Discovered
Exam report showed 0 invoice entities despite 41 emails ingested. Investigation revealed PDFs were being extracted but invoices weren't being saved to database.

### Root Causes Identified
1. **Invoice naming pattern mismatch**: Harness checked for `"invoice"`, `"inv"`, or `tx-` prefix, but exam invoices use `CDU-3051254.pdf`, `CDI-3031-0303.pdf` format
2. **Case sensitivity bug**: Code used `att_name.startswith(("TX-", "CDU-", ...))` after converting to lowercase with `att_lower = att_name.lower()`, causing pattern match to always fail
3. **Date format incompatibility**: Exam invoices use DD/MM/YYYY format (`03/06/2030`) but extractor expected YYYY-MM-DD
4. **Line item format mismatch**: Exam invoices have date at end of line (`USE2-INS2 CA51959332 Air freight 299 kg 5.69 1,701.31 19/05/2030`) vs. practice format with date at start

### Fixes Applied

#### 1. Updated harness/harness.py (lines 82-91)
```python
# Check if this looks like an invoice (TX-*, CDU-*, CDI-*, TXI-*, or contains "invoice"/"inv")
att_lower = att_name.lower()
att_upper = att_name.upper()
is_invoice = any([
    "invoice" in att_lower,
    "inv" in att_lower,
    att_upper.startswith(("TX-", "CDU-", "CDI-", "TXI-"))
])
```
**Fix**: Added `att_upper` variable and check uppercase version for prefix patterns.

#### 2. Updated harness/fallback_extractor.py - Invoice ID Pattern
```python
for pattern in [
    r'(?:INVOICE|Charges advice)\s+([A-Z]{2,3}[UI]?-\d{7,})',  # CDU-3051254, TX-US-2034-0379
    r'INVOICE\s+([A-Z]{2,3}-[A-Z]{2}-\d{4}-\d{4})',
    r'Invoice[:\s]+([A-Z]{2,3}/\d{2}-\d{2}/\d{4})',
]:
```
**Fix**: Added "Charges advice" keyword and flexible pattern for CDU-NNNNNNN format.

#### 3. Updated harness/fallback_extractor.py - Date Extraction
```python
invoice_date = self._extract_date(text, r'(?:Invoice\s+date|Document date)\s+(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})')
if invoice_date and '/' in invoice_date:
    # Convert DD/MM/YYYY to YYYY-MM-DD
    parts = invoice_date.split('/')
    invoice_date = f'{parts[2]}-{parts[1]}-{parts[0]}'
```
**Fix**: Added "Document date" keyword and DD/MM/YYYY format conversion.

#### 4. Updated harness/fallback_extractor.py - Line Item Parsing
Added new pattern before existing patterns in `_extract_invoice_lines()`:
```python
# Pattern for Caldrith exam format (date at end):
# USE2-INS2 CA51959332 Air freight 299 kg 5.69 1,701.31 19/05/2030
pattern_exam = r'([A-Z]{3,4}E?\d?)-([A-Z]{3,4}E?\d?)\s+([A-Z]{2}\d{8})\s+([A-Za-z\s]+?)\s+((?:\d+(?:\.\d+)?|[\d,]+\.?\d{2}))\s+(kg|shpt|days|%)\s+([\d.]+%?)\s+([\d,]+\.?\d{2})\s+(\d{2}/\d{2}/\d{4})'
```
**Fix**: New regex pattern matching exam format with date conversion to YYYY-MM-DD.

#### 5. Updated harness/fallback_extractor.py - Total Amount
```python
total_match = re.search(r'(?:Total|Charges)\s+(?:USD|INR)\s+([\d,]+\.?\d{2})', text, re.IGNORECASE)
```
**Fix**: Added "Charges" keyword (exam format uses "Charges USD 2,493.71" not "Total USD").

#### 6. Updated harness/extractor.py - pymupdf Pre-import
```python
# Pre-import pymupdf to ensure it's available for grader/extract.py
try:
    import pymupdf
    sys.modules['pymupdf'] = pymupdf  # Ensure it's in sys.modules
except ImportError as e:
    print(f"Warning: pymupdf not available: {e}", file=sys.stderr)
```
**Fix**: Pre-load pymupdf before importing grader/extract.py to avoid subprocess import issues.

### Results After Fix
- **Exam data**: 22 invoices extracted (was 0)
- **Practice data**: 35 invoices extracted (maintained)
- **Exam findings**: 3 total (2 waived_but_billed + 1 contract_expiry)

### Time Spent on Fix
- Debugging root cause: 25 minutes
- Implementing fixes: 20 minutes
- Testing and validation: 15 minutes
- **Total**: 60 minutes

### Lessons Learned
1. **Test both data sets early** - Exam format differences weren't caught until final hour
2. **Case sensitivity matters** - Subtle bug that took time to debug
3. **Pattern flexibility** - Real-world data has format variations that need robust patterns
4. **Incremental testing** - Should have tested invoice extraction independently before full pipeline

