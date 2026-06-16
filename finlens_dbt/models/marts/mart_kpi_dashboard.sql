WITH funnel AS (SELECT * FROM {{ ref('mart_lending_funnel') }}),
     econ   AS (SELECT * FROM {{ ref('mart_unit_economics') }})

SELECT
    f.activity_year,
    f.state_code,
    f.regulatory_era,
    f.loan_type_label,
    f.income_tier,
    f.total_applications,
    f.approval_rate,
    f.origination_rate,
    f.denial_rate,
    f.avg_loan_amount,
    f.avg_interest_rate,
    f.total_loan_volume,
    e.avg_annual_interest_revenue,
    e.est_contribution_margin,
    e.est_contribution_margin_pct,
    e.avg_ltv,
    e.avg_lti,
    e.loan_count  AS originated_loan_count

FROM funnel f
LEFT JOIN econ e
    ON  f.activity_year   = e.activity_year
    AND f.state_code      = e.state_code
    AND f.loan_type_label = e.loan_type_label
    AND f.income_tier     = e.income_tier
  