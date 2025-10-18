# Select statements

SQLETL is fully compatible with SQL.

## Data sources

Each data source listed in the FROM clause references an externel data source. Whether this source is directly listed in the FROM clause or whether it is accessed via a view.

Table names can be replaced by URIs enclosed in double quotes.

```sql
SELECT * FROM "http://example.com/path"
SELECT * FROM "postgresql://user:password@host/dbname#table"
```

To easily reference data sources it is recommended to alias them.

How a data source returns data depends on the [protocol]() and [data format]().

[Credentials](/docs/credentials), [pagination](/docs/http#pagination) and additional [headers](/docs/http#headers) can be handled by SQLify.

## Filtering results

Use the WHERE clause as usual to filter the results. Filtering is performed AFTER fetching the data.

Use the SELECT clause to list which columns the return.

LIMIT, OFFSET and ORDER BY also work as expected.

```sql
SELECT col1, col2 FROM "http://example.com/path" WHERE col1 > 0 ORDER BY col2 LIMIT 10
```

## Providing parameters

Services commonly provide query parameters to return only relevant information.

You can provide these parameters either directly in the URL or in the WHERE clause. To do the latter, prepend the parameter name with a question mark.

```sql
SELECT * FROM "http://example.com/path" WHERE "?param" = 'value'
-- GET http://example.com/path?param=value
```

If multiple parameters are provided as part of and AND expression, they will be passed on together.

Using OR expressions will result in multiple queries being performed and the data joined together.

```sql
SELECT * FROM "http://example.com/path" WHERE "?param" = 'value' OR "?param" = 'value2'

-- GET http://example.com/path?param=value
-- GET http://example.com/path?param=value2
```

AND and OR condition groups can be combined in complex expressions. SQLETL will resolve them in the appropriate number of queries.

!!! info
    Use EXPLAIN to see the query plan before executing it. (SQLify interface provides a button for that)

Parameters and conditions on columns can be combined:

```sql
SELECT * FROM "http://example.com/path" WHERE "?param" = 'value' AND col = 'value'
```

URL can also be parametrized:

```sql
SELECT * FROM "http://example.com/path/{id}" WHERE "?id" = 1
-- GET http://example.com/path/1
```

## Processing the response

Imagine an endpoint returns the following data:

    {
        "data": [
            {"key": "value", "key2": {"subkey": "value"}}
        ]
    }

The data we want as rows is located in the "data" property. Specify this using a [JSONPath](https://en.wikipedia.org/wiki/JSONPath) in the URL fragment:

```sql
SELECT * FROM "http://example.com/path#data"
```

If some of the returned columns contain nested data structures, access them using [SQL JSON operators](https://www.sqlite.org/json1.html):

```sql
SELECT key, key2->subkey FROM "http://example.com/path#data"
```

Expand a field (object) into multiple columns:

```sql
SELECT col1, EXPAND(col2) FROM "http://example.com/path"
```

Expand a field (array of objects) into multiple rows:

```sql
SELECT UNNEST(col2) FROM "http://example.com/path"
```

## Joining data

## Working with the data

GROUP BYs, WINDOW functions and other SQL features are available. SQLETL uses SQLite to process complex SQL queries when needed.

## Chaining transformations

Use CTEs to chain transformations:

```sql
WITH
    step1 AS (
        SELECT expand(col1) FROM "http://example.com/path#data" WHERE "?param" = 'value'
    ),
    step2 AS (
        SELECT * FROM step1 JOIN "other source" ON ...
    )
SELECT col1, COUNT(*) FROM step2 GROUP BY col1
```
