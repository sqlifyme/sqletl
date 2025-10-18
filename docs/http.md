# HTTP queries

Must return a [supported data format](/docs/data-formats).

    SELECT * FROM "http://example.com/path/to/rest/endpoint"
    SELECT * FROM "http://example.com/path/file.csv"

## Authentication

Use basic auth: `https://username:password@example.com`  

Use the Authorization header with a bearer token: `https://token@example.com`.

## POST requests

It is possible to perform POST requests instead of GET requests. Use "POST" in front of the URL:

```sql
SELECT * FROM "POST http://example.com/search"
```

By default paramters are provided as form encoded. You can also change this to be encoded as JSON in the body using "?json" in the URL:

```sql
SELECT * FROM "POST http://example.com/search?json" WHERE "?key" = 'value'

-- POST http://example.com/search
-- {"key": "value"}
```

The parameter name can specified nested properties and arrays:

    "?key.key" = 'value' # {"key": {"key": "value"}}
    "[].key" = 'value' # [{"key": "value"}]
    "key[]" = 'value' # {"key": ["value"]}
    "key[].key" = 'value' # {"key": [{"key": "value"}]}

All query parameters will be merged into a single JSON.

## Pagination

Some HTTP APIs will return paginated data. You can define pagination rules for some URIs.

### Using headers

When the next page number is provided through HTTP headers:

    CREATE PAGINATION ON "http://example.com/path" AS query_param = header(Header-Name)

`query_param` is the name of the query parameters that will be added to the next page request.

### Using a value from the response

Use a JSON path expression to retrieve a value from the response:

    CREATE PAGINATION ON "http://example.com/path" AS query_param = json(path.to.property)

### Listing pagination rules

    SHOW PAGINATIONS
    
### Removing a pagination rule

    DROP PAGINATION ON "http://example.com/path"

## Headers

Some HTTP endpoints will require custom headers:

    CREATE HEADER ON "http://example.com/path" AS "Header: value"

### Listing headers

    SHOW HEADERS

### Removing headers

    DROP HEADER ON "http://example.com/path"
