# Data formats

## Format detection

Format is auto-detected using (in order): Content-Type header, file extension.

Format can be forced via the URI scheme: "scheme+format://". Example: "http+csv://...", "s3+parquet://..."

## JSON

Any JSON file. Should contain either an array of objects (to return multiple rows) or a single object (returns a single row).

Combine with JSON path in the URI to select a specific path.

## CSV & XLSX

Query any CSV or XLSX files.

You can provide options via the fragment of the URI to parse the CSV.<br>

  - `header`: set to 0 to not use the first row as column names
  - `delimiter`: which delimiter to use (defaults to `,`)
  - `quote`: quotation to use (defaults to `"`)

Example:

    SELECT * FROM "http://example.com/file.csv#header=0&delimiter=;"

## Parquet

Query any Parquet file

    SELECT * FROM "http://example.com/file.parquet"

## SQLite

Query any SQLite file

    SELECT * FROM "http://example.com/file.sqlite#table"
