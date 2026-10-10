# NovaGuard Frontend Dashboard

Enterprise freight audit dashboard for visualizing NovaGuard findings and portfolio alerts.

## Features

- **Overview Metrics**: Total overpayment, cashback owed, late fees avoided, and total savings
- **Findings Table**: Searchable, filterable invoice findings with class, verdict, amount, confidence
- **Portfolio Alerts**: Cashback claims, contract expiry, and late fee risks
- **Finding Details**: Modal view with evidence quotes and source document references
- **Responsive Design**: Works on desktop, tablet, and mobile
- **Real-time Data**: Connects to backend report.json output

## Usage

### Connect to Backend

The dashboard automatically loads `../report.json` (relative to frontend directory).

To generate a report:
```bash
cd nova-takehome
python harness/harness.py report --as-of 2032-08-31 > report.json
```

Then open `frontend/index.html` in your browser.

### Demo Mode

If no backend report is available, the dashboard uses demo data from `demo-data.js`.

### File Structure

```
frontend/
├── index.html        # Main dashboard HTML
├── styles.css        # Enterprise styling (navy/neutral theme)
├── app.js            # Dashboard application logic
├── api-adapter.js    # Backend interface layer
├── demo-data.js      # Sample data for development
└── README.md         # This file
```

## Design

- **Color Palette**: Navy primary (#1e3a5f), neutral grays, semantic colors for findings
- **Typography**: System font stack, strong hierarchy, readable tables
- **Layout**: Responsive grid, card-based overview, data table for findings
- **Accessibility**: Semantic HTML, proper contrast ratios, keyboard navigation

## Integration

The dashboard is **backend-agnostic**. It only requires a JSON file matching the report schema:

```json
{
  "schema_version": "1.0",
  "as_of": "YYYY-MM-DD",
  "mode": "supervised|autonomous",
  "findings": [ /* invoice findings */ ],
  "portfolio": {
    "cashback": [ /* credit items */ ],
    "expiry": [ /* contract alerts */ ],
    "late_fee_risk": [ /* payment reminders */ ]
  }
}
```

The `APIAdapter` class handles loading and parsing. To connect to a different backend:

1. Update `loadReport(filePath)` in `api-adapter.js`
2. Or add HTTP endpoint support
3. Or add WebSocket for real-time updates

## Development

To test with custom data:

1. Edit `demo-data.js` with your sample findings
2. Open `index.html` (no build step required)
3. Or generate real report and refresh page

No frameworks, no build tools — just HTML/CSS/JS for maximum compatibility.

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (responsive design)

Requires ES6+ support (arrow functions, template literals, async/await).
