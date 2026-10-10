// NovaGuard Dashboard Application
let apiAdapter;
let currentReport = null;

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
  apiAdapter = new APIAdapter();
  setupEventListeners();
  
  // Try to load real backend data, fallback to demo
  loadInitialData();
});

function setupEventListeners() {
  document.getElementById('btn-refresh').addEventListener('click', loadInitialData);
  document.getElementById('filter-class').addEventListener('change', applyFilters);
  document.getElementById('filter-verdict').addEventListener('change', applyFilters);
  document.getElementById('filter-confidence').addEventListener('change', applyFilters);
}

async function loadInitialData() {
  // Try to load from backend report output
  const backendReport = await apiAdapter.loadReport('../report.json');
  
  if (backendReport) {
    console.log('Loaded backend report');
    currentReport = backendReport;
  } else {
    console.log('Using demo data');
    currentReport = DEMO_REPORT;
    apiAdapter.reportData = DEMO_REPORT;
  }
  
  renderDashboard();
}

function renderDashboard() {
  if (!currentReport) return;
  
  // Update metadata
  document.getElementById('as-of-date').textContent = currentReport.as_of || '-';
  document.getElementById('mode-badge').textContent = currentReport.mode || 'supervised';
  
  // Calculate and display totals
  const totals = apiAdapter.calculateTotals();
  document.getElementById('total-overpayment').textContent = formatCurrency(totals.totalOverpayment);
  document.getElementById('overpayment-count').textContent = totals.findingsCount;
  document.getElementById('cashback-owed').textContent = formatCurrency(totals.cashbackOwed);
  document.getElementById('cashback-count').textContent = totals.cashbackCount;
  document.getElementById('late-fees-avoided').textContent = formatCurrency(totals.lateFeesAvoided);
  document.getElementById('late-fee-count').textContent = totals.lateFeeCount;
  document.getElementById('total-savings').textContent = formatCurrency(totals.totalSavings);
  
  // Render findings table
  applyFilters();
  
  // Render portfolio alerts
  renderPortfolio();
}

function applyFilters() {
  const classFilter = document.getElementById('filter-class').value;
  const verdictFilter = document.getElementById('filter-verdict').value;
  const confidenceFilter = document.getElementById('filter-confidence').value;
  
  const filteredFindings = apiAdapter.filterFindings(classFilter, verdictFilter, confidenceFilter);
  renderFindingsTable(filteredFindings);
}

function renderFindingsTable(findings) {
  const tbody = document.getElementById('findings-tbody');
  
  if (!findings || findings.length === 0) {
    tbody.innerHTML = "<tr class='empty-state'><td colspan='7'>No findings match the current filters.</td></tr>";
    return;
  }
  
  tbody.innerHTML = findings.map(finding => {
    const findingJson = JSON.stringify(finding).replace(/'/g, "\\x27");
    return `<tr>
      <td><strong>${escapeHtml(finding.invoice_id || '-')}</strong></td>
      <td><span class='badge badge-${sanitizeClass(finding.class)}'>${escapeHtml(finding.class)}</span></td>
      <td><span class='badge badge-${finding.verdict}'>${escapeHtml(finding.verdict)}</span></td>
      <td>${finding.amount_usd ? formatCurrency(parseFloat(finding.amount_usd)) : '-'}</td>
      <td>${renderConfidence(finding.confidence)}</td>
      <td><code style='font-size:0.75rem'>${escapeHtml(finding.action)}</code></td>
      <td><button class='btn-view' onclick='showFindingDetail(${findingJson})'>View</button></td>
    </tr>`;
  }).join('');
}

function renderConfidence(confidence) {
  const percent = Math.round(confidence * 100);
  let level = 'high';
  if (confidence < 0.70) level = 'low';
  else if (confidence < 0.85) level = 'medium';
  
  return `<div class='confidence-bar'>
      <div class='confidence-indicator'>
        <div class='confidence-fill ${level}' style='width:${percent}%'></div>
      </div>
      <span style='font-size:0.75rem;color:var(--color-neutral-700)'>${percent}%</span>
    </div>`;
}

function renderPortfolio() {
  const portfolio = currentReport.portfolio || {};
  
  // Cashback
  const cashbackList = document.getElementById('portfolio-cashback-list');
  const cashbackItems = portfolio.cashback || [];
  document.getElementById('portfolio-cashback-count').textContent = cashbackItems.length;
  
  if (cashbackItems.length === 0) {
    cashbackList.innerHTML = '<li style="color:var(--color-neutral-700);font-size:0.875rem">No cashback items</li>';
  } else {
    cashbackList.innerHTML = cashbackItems.map(item => `<li class='alert-item'>
        <strong>${escapeHtml(item.contract_id || '')}</strong>
        ${item.period}: ${formatCurrency(parseFloat(item.amount_usd || 0))}
        <div style='font-size:0.75rem;color:var(--color-neutral-700);margin-top:0.25rem'>
          ${escapeHtml(item.credit_type || '')}
        </div>
      </li>`).join('');
  }
  
  // Expiry
  const expiryList = document.getElementById('portfolio-expiry-list');
  const expiryItems = portfolio.expiry || [];
  document.getElementById('portfolio-expiry-count').textContent = expiryItems.length;
  
  if (expiryItems.length === 0) {
    expiryList.innerHTML = '<li style="color:var(--color-neutral-700);font-size:0.875rem">No expiring contracts</li>';
  } else {
    expiryList.innerHTML = expiryItems.map(item => `<li class='alert-item'>
        <strong>${escapeHtml(item.contract_id || '')}</strong>
        Deadline: ${item.deadline || '-'}
      </li>`).join('');
  }
  
  // Late Fee Risk
  const lateFeeList = document.getElementById('portfolio-late-fee-risk-list');
  const lateFeeItems = portfolio.late_fee_risk || [];
  document.getElementById('portfolio-late-fee-count').textContent = lateFeeItems.length;
  
  if (lateFeeItems.length === 0) {
    lateFeeList.innerHTML = '<li style="color:var(--color-neutral-700);font-size:0.875rem">No late fee risks</li>';
  } else {
    lateFeeList.innerHTML = lateFeeItems.map(item => `<li class='alert-item'>
        <strong>${escapeHtml(item.invoice_id || '')}</strong>
        Due: ${item.deadline || '-'} — Risk: ${formatCurrency(parseFloat(item.amount_usd || 0))}
      </li>`).join('');
  }
}

function showFindingDetail(finding) {
  const modal = document.getElementById('detail-modal');
  const title = document.getElementById('modal-title');
  const body = document.getElementById('modal-body');
  
  title.textContent = `Finding: ${finding.invoice_id || finding.contract_id || finding.id}`;
  
  let html = `<div class='detail-section'>
      <h3>Details</h3>
      <p><strong>Class:</strong> ${escapeHtml(finding.class)}</p>
      <p><strong>Verdict:</strong> <span class='badge badge-${finding.verdict}'>${escapeHtml(finding.verdict)}</span></p>`;
  
  if (finding.amount_usd) {
    html += `<p><strong>Amount:</strong> ${formatCurrency(parseFloat(finding.amount_usd))}</p>`;
  }
  
  html += `<p><strong>Action:</strong> <code>${escapeHtml(finding.action)}</code></p>
      <p><strong>Confidence:</strong> ${Math.round(finding.confidence * 100)}%</p>
    </div>
    
    <div class='detail-section'>
      <h3>Evidence</h3>
      ${renderEvidence(finding.evidence || [])}
    </div>`;
    
  if (finding.missing_doc) {
    html += `<div class='detail-section'>
        <h3>Missing Document</h3>
        <p><strong>Name:</strong> ${escapeHtml(finding.missing_doc.name)}</p>
        <p><strong>Holder:</strong> ${escapeHtml(finding.missing_doc.holder?.person || finding.missing_doc.holder?.party || '-')}</p>
      </div>`;
  }
  
  if (finding.amount_range) {
    html += `<div class='detail-section'>
        <h3>Amount Range (Conflict)</h3>
        <p>${formatCurrency(parseFloat(finding.amount_range[0]))} - ${formatCurrency(parseFloat(finding.amount_range[1]))}</p>
      </div>`;
  }
  
  body.innerHTML = html;
  modal.classList.add('active');
}

function renderEvidence(evidence) {
  if (!evidence || evidence.length === 0) {
    return '<p style="color:var(--color-neutral-700)">No evidence provided</p>';
  }
  
  return `<ul class='evidence-list'>${evidence.map(item => `<li class='evidence-item'>
        <div class='evidence-doc'>📄 ${escapeHtml(item.doc)} (page ${item.page})</div>
        <div class='evidence-quote'>${escapeHtml(item.quote)}</div>
      </li>`).join('')}</ul>`;
}

function closeModal() {
  document.getElementById('detail-modal').classList.remove('active');
}

// Utility functions
function formatCurrency(value) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }).format(value);
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function sanitizeClass(className) {
  return className.replace(/_/g, '-');
}
