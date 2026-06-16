WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
    WHERE is_originated = 1
)

SELECT
    activity_year,
    vintage_label,
    regulatory_era,
    rate_era,
    state_code,
    loan_type_label,
    loan_size_tier,
    income_tier,
    is_investor_loan,

    COUNT(*)                                                            AS loan_count,
    ROUND(AVG(loan_amount), 0)                                          AS avg_loan_amount,
    ROUND(SUM(loan_amount), 0)                                          AS total_loan_volume,
    ROUND(AVG(annual_interest_revenue_proxy), 0)                        AS avg_annual_interest_revenue,
    ROUND(SUM(annual_interest_revenue_proxy), 0)                        AS total_interest_revenue_proxy,
    ROUND(AVG(loan_amount) * 0.015, 0)                                  AS est_origination_cost_per_loan,
    ROUND(AVG(loan_amount) * 0.003, 0)                                  AS est_annual_servicing_cost,
    ROUND(
        AVG(annual_interest_revenue_proxy)
        - AVG(loan_amount) * 0.015
        - AVG(loan_amount) * 0.003,
    0)                                                                  AS est_contribution_margin,
    ROUND(
        SAFE_DIVIDE(
            AVG(annual_interest_revenue_proxy)
            - AVG(loan_amount) * 0.015
            - AVG(loan_amount) * 0.003,
            AVG(loan_amount)
        ),
    4)                                                                  AS est_contribution_margin_pct,
    ROUND(AVG(ltv_ratio_derived), 3)                                    AS avg_ltv,
    ROUND(AVG(loan_to_income_ratio), 3)                                 AS avg_lti,
    ROUND(AVG(cltv_ratio), 3)                                           AS avg_cltv

FROM base
GROUP BY 1,2,3,4,5,6,7,8,9

