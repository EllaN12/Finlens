WITH hmda AS (
    SELECT * FROM {{ ref('stg_hmda_lar') }}
),
macro AS (
    SELECT * FROM {{ ref('stg_fred_macro') }}
)

SELECT
    h.*,
    m.unemployment_rate,
    m.hpi,
    m.mortgage_rate_30yr,

    -- Derived financial ratios
    ROUND(h.loan_amount / NULLIF(h.income_annual, 0), 2)            AS loan_to_income_ratio,
    ROUND(h.loan_amount / NULLIF(h.property_value, 0), 2)           AS ltv_ratio_derived,
    ROUND(h.loan_amount * (h.interest_rate / 100), 0)               AS annual_interest_revenue_proxy,

    -- DiD treatment flags
    IF(h.state_code = 'CA', 1, 0)                                   AS is_california,
    IF(h.activity_year >= 2020, 1, 0)                               AS is_post_ccpa,
    IF(h.state_code = 'CA' AND h.activity_year >= 2020, 1, 0)       AS is_treated,

    -- Staggered DiD flags
    CASE
        WHEN h.state_code = 'CA' AND h.activity_year >= 2020 THEN 1
        WHEN h.state_code = 'VA' AND h.activity_year >= 2023 THEN 1
        WHEN h.state_code = 'CO' AND h.activity_year >= 2023 THEN 1
        ELSE 0
    END                                                             AS is_treated_staggered,

    CASE
        WHEN h.state_code = 'CA' THEN 2020
        WHEN h.state_code = 'VA' THEN 2023
        WHEN h.state_code = 'CO' THEN 2023
        ELSE NULL
    END                                                             AS treatment_year

FROM hmda h
LEFT JOIN macro m
    ON  h.state_code    = m.state_code
    AND h.activity_year = m.macro_year