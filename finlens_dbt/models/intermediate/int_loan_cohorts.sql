WITH base AS (
    SELECT * FROM {{ ref('int_approval_flags') }}
)

SELECT
    *,
    CONCAT('VTG-', CAST(activity_year AS STRING))   AS vintage_label,

    CASE
        WHEN activity_year BETWEEN 2018 AND 2019 THEN 'pre_ccpa'
        WHEN activity_year = 2020               THEN 'ccpa_transition'
        WHEN activity_year BETWEEN 2021 AND 2023 THEN 'post_ccpa'
    END                                             AS regulatory_era,

    CASE
        WHEN activity_year BETWEEN 2018 AND 2021 THEN 'low_rate_era'
        WHEN activity_year BETWEEN 2022 AND 2023 THEN 'rising_rate_era'
    END                                             AS rate_era,

    IF(occupancy_type = 2 AND action_taken_code IN (1,2), 1, 0) AS is_investor_loan

FROM base