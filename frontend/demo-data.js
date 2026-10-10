// Demo data for UI development and testing
const DEMO_REPORT = {
  schema_version: '1.0',
  as_of: '2032-08-31',
  mode: 'supervised',
  findings: [
    {
      id: 'overcharge:TX-US-2032-5394',
      class: 'overcharge',
      invoice_id: 'TX-US-2032-5394',
      verdict: 'finding',
      amount_usd: '196.92',
      action: 'draft:dispute',
      confidence: 0.95,
      evidence: [
        {
          doc: 'batch_01/0003.eml#TX-US-2032-5394.pdf',
          page: 1,
          quote: '1 TE56915687 2031-12-25 Air freight USE2-INE2 241 kg 6.69 1612.29'
        },
        {
          doc: 'batch_01/0002.eml#MSA-TBX-US-EXP-E60.pdf',
          page: 8,
          quote: 'USE2-INE2 100-299.5 kg 6.01 6.16'
        }
      ],
      missing_doc: null,
      amount_range: null,
      deadline: null,
      supersedes: [],
      retro: false,
      learned_at: null
    },
    {
      id: 'no_finding:TX-US-2032-5397',
      class: 'overcharge',
      invoice_id: 'TX-US-2032-5397',
      verdict: 'no_finding',
      amount_usd: null,
      action: 'none',
      confidence: 0.90,
      evidence: [
        {
          doc: 'batch_01/0004.eml#TX-US-2032-5397.pdf',
          page: 1,
          quote: '1 TE68271803 2032-01-18 Air freight USE2-INE2 44 kg 7.73 340.12'
        }
      ],
      missing_doc: null,
      amount_range: null,
      deadline: null,
      supersedes: [],
      retro: false,
      learned_at: null
    }
  ],
  portfolio: {
    cashback: [],
    expiry: [],
    late_fee_risk: []
  }
};

// Make available globally
if (typeof window !== 'undefined') {
  window.DEMO_REPORT = DEMO_REPORT;
}
