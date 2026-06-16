WITH source AS (
    SELECT * FROM {{ source('fred', 'fred_macro_raw') }}
)

SELECT
    state_code,
    DATE_TRUNC(period_date, YEAR)                               AS macro_year_date,
    EXTRACT(YEAR FROM period_date)                              AS macro_year,
    AVG(IF(metric_name = 'unemployment_rate', value, NULL))     AS unemployment_rate,
    AVG(IF(metric_name = 'hpi',               value, NULL))     AS hpi,
    AVG(IF(metric_name = 'mortgage_rate_30yr', value, NULL))    AS mortgage_rate_30yr
FROM source
WHERE EXTRACT(YEAR FROM period_date) BETWEEN {{ var('start_year') - 1 }} AND {{ var('end_year') }}
GROUP BY 1, 2, 3