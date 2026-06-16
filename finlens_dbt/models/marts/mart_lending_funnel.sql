WITH base AS (
    SELECT * FROM {{ ref('int_loan_cohorts') }}
)

SELECT
    activity_year,
    state_code,
    regulatory_era,
    loan_type_label,
    loan_purpose_label,
    loan_size_tier,
    income_tier,

    COUNT(*)                                                        AS total_applications,
    SUM(is_approved)                                                AS total_approved,
    SUM(is_originated)                                              AS total_originated,
    SUM(is_denied)                                                  AS total_denied,
    SUM(is_withdrawn_or_incomplete)                                 AS total_withdrawn,

    ROUND(SAFE_DIVIDE(SUM(is_approved),   COUNT(*)), 4)             AS approval_rate,
    ROUND(SAFE_DIVIDE(SUM(is_originated), COUNT(*)), 4)             AS origination_rate,
    ROUND(SAFE_DIVIDE(SUM(is_denied),     COUNT(*)), 4)             AS denial_rate,
    ROUND(SAFE_DIVIDE(SUM(is_originated), SUM(is_approved)), 4)    AS close_rate,

    ROUND(AVG(IF(is_originated=1, loan_amount,    NULL)), 0)        AS avg_loan_amount,
    ROUND(SUM(IF(is_originated=1, loan_amount,    0)),    0)        AS total_loan_volume,
    ROUND(AVG(IF(is_originated=1, interest_rate,  NULL)), 3)        AS avg_interest_rate

FROM base
GROUP BY 1,2,3,4,5,6,7
