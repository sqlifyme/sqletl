# sqletl

Create ETL pipelines using SQL to extract data from HTTP and other sources.

sqletl lets you query remote data as if it were a table: put a URI in the `FROM` clause and
sqletl fetches, parses and transforms the data. Join an API with a CSV on S3, filter it, aggregate
it and export the result, all in a single SQL statement.

```sql
SELECT u.name, COUNT(*) AS orders
FROM "https://api.example.com/users#data" u
JOIN "s3:///my-bucket/orders.parquet" o ON o.user_id = u.id
GROUP BY u.name
```

## Features

- **Sources (protocols):** HTTP(S) (GET and POST), local files, S3 and S3-compatible storage,
  FTP, PostgreSQL, MySQL, Google Sheets
- **Formats:** JSON, CSV, XLSX, Parquet, SQLite (auto-detected from the Content-Type header or
  file extension, or forced with `scheme+format://`, e.g. `http+csv://...`)
- **Query parameters from SQL:** `WHERE "?param" = 'value'` is sent to the source as a request
  parameter; `OR` conditions fan out into multiple requests whose results are merged
- **URL templates:** `"https://example.com/users/{id}"` with `WHERE "?id" = 1`
- **Nested data:** select rows with a JSONPath in the URI fragment (`#data.items`), access
  fields with `->` / `->>`, flatten with `EXPAND()` (object to columns) and `UNNEST()` (array to rows)
- **Full SQL processing:** joins, `GROUP BY`, window functions, `ORDER BY`, `LIMIT`, CTEs
  (`WITH`) to chain steps (complex operations run on SQLite)
- **Export** to CSV, JSON, XLSX, Parquet, HTML, Markdown or SQL

## Installation

Requires Python 3.10+. The `postgres-proto` dependency is currently resolved from a sibling
checkout (`../postgres-proto`).

```sh
uv sync          # or: pip install .
```

## Usage

### Command line

```sh
# Print results as a table
sqletl 'SELECT * FROM "https://example.com/api/items#data" LIMIT 10'

# Show the query plan without executing it
sqletl -e "SELECT * FROM \"https://example.com/api/items\" WHERE \"?q\" = 'a' OR \"?q\" = 'b'"

# Write results to a file (format taken from the extension)
sqletl -o out.parquet 'SELECT * FROM "file://data.csv#delimiter=;"'
```

Run `sqletl` without arguments to be prompted for a statement.

### Python

```python
from sqletl import execute

dt = execute('SELECT name, age FROM "file://people.csv" WHERE age > 30')
df = dt.to_dataframe()  # pandas DataFrame
```

## Source examples

```sql
SELECT * FROM "https://user:pass@example.com/api"           -- basic auth
SELECT * FROM "https://token@example.com/api"               -- bearer token
SELECT * FROM "POST https://example.com/search?json" WHERE "?query" = 'x'
SELECT * FROM "s3://key:secret@/bucket/file.csv?region_name=eu-west-1"
SELECT * FROM "postgresql://user:pass@host/dbname#table"
SELECT * FROM "mysql://user:pass@host/dbname#table"
SELECT * FROM "ftp://user:pass@host/file.xlsx"
SELECT * FROM "gsheets://token@spreadsheetId/sheetId"
```

## Documentation

See the [docs/](docs/) folder for details on [queries](docs/index.md), [HTTP](docs/http.md),
[protocols](docs/protocols.md), [data formats](docs/data-formats.md) and
[limitations](docs/limitations.md).

sqletl is in beta: sub-selects, multiple sources in `FROM` (use `JOIN`), `OR` in join
conditions, and combining aggregates with `EXPAND`/`UNNEST` are not supported yet.

## Development

```sh
uv run pytest
```

## License

MIT
