# Technical Details - Overcharge Fix Implementation

## Business Logic Implementation

### Overcharge Formula (from GLOSSARY.md)
```
Overcharge = (billed_freight + billed_fuel) - (correct_freight + correct_fuel)

Where:
- correct_fuel = fuel_percentage × correct_freight
- fuel_percentage = lookup from Annex C by pickup month
```

### Example Calculation
```
Invoice: TX-US-2032-5394
Pickup: 2031-12-15
Fuel rate (2031-12): 20.16%

Billed amounts:
- Freight: 1645.33
- Fuel: 292.00
- Total: 1937.33

Correct amounts:
- Freight: 1448.41 (241 kg × $6.01/kg)
- Fuel: 292.00 (20.16% × 1448.41)
- Total: 1740.41

Overcharge: 1937.33 - 1740.41 = 196.92 ✓
```

---

## Code Changes Detail

### 1. Fuel Table Pattern Fix

**File**: `harness/fallback_extractor.py`  
**Line**: ~273

**Before**:
```python
pattern = r'(\d{4}-\d{2})\s*\|\s*([\d.]+)%'
# Expected format: 2031-12 | 20.16%
```

**After**:
```python
pattern = r'(\d{4}-\d{2})\s+(\d+\.\d+)%'
# Actual format in PDFs: 2031-12 20.16%
```

**Reason**: Real PDF tables use space-separated values, not pipe-separated

**Impact**: 
- Before: 0 fuel surcharges extracted
- After: 13 fuel surcharges extracted from MSA-TBX-US-EXP-E60.pdf

---

### 2. Overcharge Detection Rewrite

**File**: `harness/business_rules.py`  
**Lines**: Multiple sections

#### Added Fuel Surcharge Fetching (line ~66)
```python
fuel_surcharges = self.state.get_entities("fuel_surcharge", as_of=as_of)
```

#### Added Fuel Map Building (line ~74)
```python
fuel_map = self._build_fuel_map(fuel_surcharges)
```

#### Added Fuel Map Method (line ~218)
```python
def _build_fuel_map(self, fuel_surcharges: list) -> dict:
    """Build month -> percentage map from fuel surcharge entities."""
    fuel_map = {}
    for fs in fuel_surcharges:
        month = fs.get("month")  # format: YYYY-MM
        percentage = fs.get("percentage")
        if month and percentage is not None:
            fuel_map[month] = percentage
    return fuel_map
```

#### Updated Overcharge Detection Signature (line ~236)
```python
def _detect_overcharges(self, invoices, rates, msas, amendments, fuel_map, as_of):
    # Added fuel_map parameter
```

#### Rewrote Detection Logic (line ~256-340)

**Key Changes**:
1. Group invoice lines by AWB
2. Separate freight lines from fuel lines
3. For each AWB with discrepancy:
   - Calculate billed_freight and billed_fuel totals
   - Calculate correct_freight based on rate lookup
   - Recalculate correct_fuel = fuel_percentage × correct_freight
   - Overcharge = (billed_freight + billed_fuel) - (correct_freight + correct_fuel)

**Pseudo-code**:
```python
# Group lines by AWB
awb_groups = {}
for line in invoice["line_items"]:
    awb = line["awb"]
    if "fuel" in line["charge_type"].lower():
        awb_groups[awb]["fuel_lines"].append(line)
    else:
        awb_groups[awb]["freight_lines"].append(line)

# Process each AWB
for awb, group in awb_groups.items():
    # Calculate billed totals
    billed_freight = sum(line["amount_usd"] for line in group["freight_lines"])
    billed_fuel = sum(line["amount_usd"] for line in group["fuel_lines"])
    
    # Find correct rate and calculate correct freight
    correct_freight = calculate_correct_freight(group["freight_lines"], rates)
    
    # Lookup fuel percentage by pickup month
    pickup_month = extract_month(invoice["pickup_date"])  # YYYY-MM
    fuel_pct = fuel_map.get(pickup_month, 0)
    
    # Recalculate fuel on correct freight
    correct_fuel = correct_freight * fuel_pct
    
    # Calculate overcharge
    if abs((billed_freight + billed_fuel) - (correct_freight + correct_fuel)) > 0.01:
        overcharge_amount = (billed_freight + billed_fuel) - (correct_freight + correct_fuel)
        # Create finding...
```

---

### 3. Removed Duplicate Method

**File**: `harness/claude_extractor.py`

**Removed**: Duplicate `extract_fuel_surcharge_table()` method that was identical to the one in `fallback_extractor.py`

**Reason**: DRY principle, avoid confusion

---

## Charge Type Detection

### Fuel Line Identification
```python
# Only lines with "fuel" in charge_type are fuel lines
is_fuel = "fuel" in line.get("charge_type", "").lower()
```

**Rejected Approach**:
```python
# This incorrectly caught security surcharge and delivery fees
is_fuel = "surcharge" in charge_type and not line.get("weight_kg")
```

**Why**: 
- Security surcharge is NOT fuel surcharge
- Delivery fee surcharge is NOT fuel surcharge
- Only lines explicitly marked as "fuel" should be treated as fuel

---

## Python Environment Issue

### Root Cause
```
Global python: Missing pymupdf module
Venv python: Has pymupdf installed

Grader calling "python" → uses global python → extraction fails → 0/100
```

### Solution
Use explicit venv python path:
```powershell
C:/Users/tharu/nova-takehome/.venv/Scripts/python.exe
```

---

## Windows PowerShell Path Escaping

### Problem
```python
import shlex
path = r"C:\Users\tharu\nova-takehome\.venv\Scripts\python.exe"
result = shlex.split(path)
# Result: ['C:Userstharunova-takehome.venvScriptspython.exe']
# All backslashes stripped!
```

### Root Cause
`shlex.split()` treats backslashes as escape characters, even on Windows

### Solution
Use forward slashes (Windows accepts both):
```powershell
C:/Users/tharu/nova-takehome/.venv/Scripts/python.exe
```

This works because:
1. Windows file system accepts `/` and `\` interchangeably
2. `shlex.split()` doesn't strip forward slashes
3. Result: `['C:/Users/tharu/nova-takehome/.venv/Scripts/python.exe']` ✓

---

## Test Infrastructure

### Manual Overcharge Test
```bash
# Clean state
Remove-Item -Recurse -Force .test-state

# Ingest
python harness/harness.py ingest --state-dir .test-state data/examples/overcharge/docs/batch_01

# Report
python harness/harness.py report --state-dir .test-state --as-of 2032-08-31 --mode supervised

# Expected output:
# {
#   "findings": [
#     {
#       "id": "overcharge:TX-US-2032-5394",
#       "amount_usd": "196.92",  # ← Must match this
#       ...
#     }
#   ]
# }
```

### Practice Grader
```bash
python grader/run_grader.py \
  --harness "python harness/harness.py" \
  --data data/scenarios \
  --key data/scenarios/answers \
  --mode both \
  --timeout 600
```

### Evaluation Suite
```bash
python evals/run_evals.py --harness harness/harness.py
```

---

## Data Structures

### Fuel Surcharge Entity
```python
{
    "type": "fuel_surcharge",
    "month": "2031-12",         # YYYY-MM format
    "percentage": 20.16,        # decimal, not 0.2016
    "source_doc": "0002.eml#MSA-TBX-US-EXP-E60.pdf",
    "page": 9
}
```

### Invoice Line Item
```python
{
    "awb": "TBX-01234567",
    "charge_type": "Air freight" or "Fuel surcharge",
    "amount_usd": 1645.33,
    "weight_kg": 241.0,
    "origin": "USE2",
    "dest": "INE2"
}
```

### Rate Entity
```python
{
    "type": "rate",
    "lane": "USE2-INE2",
    "weight_min": 100.0,
    "weight_max": 299.5,
    "rate_per_kg": 6.01,
    "effective_from": "2031-06-01",
    "source_doc": "0002.eml#MSA-TBX-US-EXP-E60.pdf",
    "page": 8
}
```

---

## Performance Metrics

### Detection Accuracy
```
Hits: 6
False Positives: 5
Misses: 16
Precision: 0.27
Recall: 0.14
F1: 0.18
```

### Amount Accuracy
```
Total at stake: $14,140.09
Recovered: $562.38 (3.98%)
Wrongly disputed: $706.74
Net: -$144.36
```

### Category Breakdown
```
Class                Hits  False  Missed    F1
waived_but_billed      3      0       0   0.50 ✓
overcharge             3      1       6   0.23
late_fee_risk          0      4       1   0.00
duplicate              0      0       3   0.00
late_fee_not_owed      0      0       3   0.00
cashback               0      0       2   0.00
expiry                 0      0       1   0.00
```

---

## Known Limitations

1. **Conflict Detection**: Not implemented (sample_conflict.yaml fails)
2. **Duplicate Detection**: Not catching TX-US-2034-0386
3. **Cashback**: Not detecting TBX-US-EXP-01/2035-Q1/rebate
4. **Late Fees**: Missing TX-US-2035-0215, TX-US-2035-0265
5. **False Positives**: 5 items wrongly flagged (mostly late_fee_risk)

---

**End of Technical Details**
