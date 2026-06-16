WITH base AS (
    SELECT * FROM {{ ref('int_applications_enriched') }}
)

SELECT
    *,
    IF(action_taken_code IN (1, 2, 8), 1, 0)  AS is_approved,
    IF(action_taken_code = 1, 1, 0)            AS is_originated,
    IF(action_taken_code IN (3, 7), 1, 0)      AS is_denied,
    IF(action_taken_code IN (4, 5), 1, 0)      AS is_withdrawn_or_incomplete,

    CASE denial_reason_1
        WHEN 1 THEN 'debt_to_income'
        WHEN 2 THEN 'employment_history'
        WHEN 3 THEN 'credit_history'
        WHEN 4 THEN 'collateral'
        WHEN 5 THEN 'insufficient_cash'
        WHEN 6 THEN 'unverifiable_info'
        WHEN 7 THEN 'credit_app_incomplete'
        WHEN 8 THEN 'mortgage_insurance_denied'
        WHEN 9 THEN 'other'
        ELSE NULL
    END                                        AS denial_reason_label,

    CASE
        WHEN income_annual < 50000                       THEN 'low_income'
        WHEN income_annual BETWEEN 50000 AND 99999       THEN 'moderate_income'
        WHEN income_annual BETWEEN 100000 AND 199999     THEN 'middle_income'
        WHEN income_annual >= 200000                     THEN 'high_income'
        ELSE 'unknown'
    END                                        AS income_tier,

    CASE
        WHEN loan_amount < 150000                        THEN 'small'
        WHEN loan_amount BETWEEN 150000 AND 417000       THEN 'conforming'
        WHEN loan_amount > 417000                        THEN 'jumbo'
        ELSE 'unknown'
    END                                        AS loan_size_tier

FROM base