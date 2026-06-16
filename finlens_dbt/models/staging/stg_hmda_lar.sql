WITH source AS (
    SELECT * FROM {{ source('hmda', 'hmda_lar_raw') }}
),

cleaned AS (
    SELECT
        CAST(activity_year AS INT64)                            AS activity_year,
        state_code,
        county_code,
        DATE(CAST(activity_year AS INT64), 7, 1)               AS application_mid_year_date,

        -- Action classification
        CAST(action_taken AS INT64)                             AS action_taken_code,
        CASE CAST(action_taken AS INT64)
            WHEN 1 THEN 'originated'
            WHEN 2 THEN 'approved_not_accepted'
            WHEN 3 THEN 'denied'
            WHEN 4 THEN 'withdrawn'
            WHEN 5 THEN 'incomplete'
            WHEN 6 THEN 'purchased'
            WHEN 7 THEN 'preapproval_denied'
            WHEN 8 THEN 'preapproval_approved'
            ELSE 'unknown'
        END                                                     AS action_taken_label,

        -- Loan attributes
        CAST(loan_type AS INT64)                                AS loan_type_code,
        CASE CAST(loan_type AS INT64)
            WHEN 1 THEN 'conventional'
            WHEN 2 THEN 'fha'
            WHEN 3 THEN 'va'
            WHEN 4 THEN 'usda'
        END                                                     AS loan_type_label,
        CAST(loan_purpose AS INT64)                             AS loan_purpose_code,
        CASE CAST(loan_purpose AS INT64)
            WHEN 1  THEN 'purchase'
            WHEN 2  THEN 'home_improvement'
            WHEN 31 THEN 'refinance'
            WHEN 32 THEN 'cash_out_refinance'
            WHEN 4  THEN 'other'
        END                                                     AS loan_purpose_label,
        derived_loan_product_type                               AS loan_product_type,
        derived_dwelling_category                               AS dwelling_category,
        CAST(lien_status AS INT64)                             AS lien_status,
        CAST(occupancy_type AS INT64)                          AS occupancy_type,

        -- Financial metrics
        SAFE_CAST(loan_amount AS FLOAT64)                       AS loan_amount,
        SAFE_CAST(property_value AS FLOAT64)                    AS property_value,
        SAFE_CAST(interest_rate AS FLOAT64)                     AS interest_rate,
        SAFE_CAST(rate_spread AS FLOAT64)                       AS rate_spread,
        SAFE_CAST(combined_loan_to_value_ratio AS FLOAT64)      AS cltv_ratio,
        SAFE_CAST(income AS FLOAT64)                            AS income_thousands,
        SAFE_CAST(income AS FLOAT64) * 1000                     AS income_annual,
        debt_to_income_ratio                                    AS dti_bucket,
        SAFE_CAST(loan_term AS INT64)                           AS loan_term_months,

        -- Denial reasons
        SAFE_CAST(denial_reason_1 AS INT64)                     AS denial_reason_1,
        SAFE_CAST(denial_reason_2 AS INT64)                     AS denial_reason_2,

        -- Demographics
        derived_race                                            AS applicant_race,
        derived_sex                                             AS applicant_sex,
        applicant_age                                           AS applicant_age_bucket,

        -- Quality flags
        IF(SAFE_CAST(loan_amount AS FLOAT64)   IS NULL, 1, 0)  AS flag_missing_loan_amount,
        IF(SAFE_CAST(income AS FLOAT64)        IS NULL, 1, 0)  AS flag_missing_income,
        IF(SAFE_CAST(interest_rate AS FLOAT64) IS NULL, 1, 0)  AS flag_missing_rate,

        _loaded_at

    FROM source
    WHERE CAST(activity_year AS INT64) BETWEEN {{ var('start_year') }} AND {{ var('end_year') }}
      AND state_code IS NOT NULL
      AND CAST(action_taken AS INT64) BETWEEN 1 AND 8
)

SELECT * FROM cleaned