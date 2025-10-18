# Limitations

SQLETL is still in BETA and being actively developed. Some limitations apply.

 - No sub-select
 - Multiple sources in FROM clause are not supported, use JOIN instead
 - JOIN ON clauses have limited capabilities
 - Use `CONCAT(a, b, ...)` in JOIN ON clauses to concatenate strings
 - No OR expressions in JOIN ON clauses
 - Aggregates and EXPAND/UNNEST functions are not supported together
