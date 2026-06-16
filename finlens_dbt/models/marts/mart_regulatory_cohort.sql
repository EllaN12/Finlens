WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
    WHERE state_code IN ('CA','TX','FL','OH','NY','IL','WA','CO','VA')
)

SELECT
    activity_year,
    state_code,
    regulatory_era,
    is_california,
    is_post_ccpa,
    is_treated,
    is_treated_staggered,
    treatment_year,
    loan_type_label,
    loan_purpose_label,
    income_tier,
    is_investor_loan,

    COUNT(*)                                                        AS n_applications,
    SUM(is_approved)                                                AS n_approved,
    SUM(is_originated)                                              AS n_originated,
    ROUND(AVG(CAST(is_approved AS FLOAT64)), 4)                    AS approval_rate,
    ROUND(AVG(CAST(is_originated AS FLOAT64)), 4)                  AS origination_rate,
    ROUND(AVG(CAST(is_denied AS FLOAT64)), 4)                      AS denial_rate,
    ROUND(AVG(IF(is_approved=1, loan_amount,  NULL)), 0)           AS avg_approved_loan_amount,
    ROUND(AVG(IF(is_approved=1, income_annual,NULL)), 0)           AS avg_approved_income,
    ROUND(AVG(CAST(flag_missing_income AS FLOAT64)), 4)            AS pct_missing_income,
    ROUND(AVG(IF(is_approved=1, interest_rate,NULL)), 4)           AS avg_interest_rate,
    ROUND(AVG(IF(is_approved=1, ltv_ratio_derived,NULL)), 4)       AS avg_ltv,
    -- DTI: map HMDA bucket labels to numeric midpoints, then average
    ROUND(AVG(CASE dti_bucket
        WHEN '<20%'      THEN 15.0
        WHEN '20%-<30%'  THEN 25.0
        WHEN '30%-<36%'  THEN 33.0
        WHEN '36%-<50%'  THEN 43.0
        WHEN '50%-<60%'  THEN 55.0
        WHEN '>60%'      THEN 65.0
        ELSE NULL
    END), 2)                                                        AS avg_dti,
    AVG(unemployment_rate)                                          AS unemployment_rate,
    AVG(hpi)                                                        AS hpi,
    AVG(mortgage_rate_30yr)                                         AS mortgage_rate_30yr

FROM base
GROUP BY 1,2,3,4,5,6,7,8,9,10,11,12
