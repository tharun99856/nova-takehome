// API Adapter - connects to backend report output
class APIAdapter {
  constructor() {
    this.reportData = null;
  }

  // Load report from backend JSON file
  async loadReport(filePath) {
    try {
      const response = await fetch(filePath);
      if (!response.ok) throw new Error('Failed to load report');
      this.reportData = await response.json();
      return this.reportData;
    } catch (error) {
      console.warn('Backend report not available:', error);
      return null;
    }
  }

  // Load report from file input
  loadReportFromFile(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          this.reportData = JSON.parse(e.target.result);
          resolve(this.reportData);
        } catch (error) {
          reject(error);
        }
      };
      reader.onerror = reject;
      reader.readAsText(file);
    });
  }

  // Get current report data
  getReport() {
    return this.reportData;
  }

  // Calculate totals
  calculateTotals() {
    if (!this.reportData) {
      return {
        totalOverpayment: 0,
        cashbackOwed: 0,
        lateFeesAvoided: 0,
        totalSavings: 0,
        findingsCount: 0,
        cashbackCount: 0,
        lateFeeCount: 0,
        expiryCount: 0
      };
    }

    const findings = this.reportData.findings || [];
    const portfolio = this.reportData.portfolio || {};

    // Total overpayment from invoice findings
    const totalOverpayment = findings
      .filter(f => f.verdict === 'finding' && f.amount_usd)
      .reduce((sum, f) => sum + parseFloat(f.amount_usd), 0);

    // Cashback owed
    const cashbackItems = portfolio.cashback || [];
    const cashbackOwed = cashbackItems
      .filter(f => f.verdict === 'finding' && f.amount_usd)
      .reduce((sum, f) => sum + parseFloat(f.amount_usd), 0);

    // Late fees avoided
    const lateFeeItems = portfolio.late_fee_risk || [];
    const lateFeesAvoided = lateFeeItems
      .filter(f => f.verdict === 'finding' && f.amount_usd)
      .reduce((sum, f) => sum + parseFloat(f.amount_usd), 0);

    // Total savings
    const totalSavings = totalOverpayment + cashbackOwed + lateFeesAvoided;

    return {
      totalOverpayment,
      cashbackOwed,
      lateFeesAvoided,
      totalSavings,
      findingsCount: findings.filter(f => f.verdict === 'finding').length,
      cashbackCount: cashbackItems.length,
      lateFeeCount: lateFeeItems.length,
      expiryCount: (portfolio.expiry || []).length
    };
  }

  // Filter findings
  filterFindings(classFilter, verdictFilter, confidenceFilter) {
    if (!this.reportData) return [];

    let findings = [...(this.reportData.findings || [])];

    if (classFilter !== 'all') {
      findings = findings.filter(f => f.class === classFilter);
    }

    if (verdictFilter !== 'all') {
      findings = findings.filter(f => f.verdict === verdictFilter);
    }

    if (confidenceFilter !== 'all') {
      findings = findings.filter(f => {
        const conf = f.confidence;
        if (confidenceFilter === 'high') return conf >= 0.85;
        if (confidenceFilter === 'medium') return conf >= 0.70 && conf < 0.85;
        if (confidenceFilter === 'low') return conf < 0.70;
        return true;
      });
    }

    return findings;
  }
}

// Export for use in app.js
if (typeof window !== 'undefined') {
  window.APIAdapter = APIAdapter;
}
