# Protocols

## HTTP(S)

See the [dedicated section](/docs/http).

## S3

Query files located on S3 buckets (pay attention to the triple slashes).

    SELECT * FROM "s3:///bucket-name/file.csv"

Private buckets require authentication:

    SELECT * FROM "s3://aws_key:aws_secret@/bucket-name/file.csv"

In some cases, you may need to specify the region:

    SELECT * FROM "s3:///bucket-name/file.csv?region_name=us-east-1"

You can also use any S3 compatible service:

    SELECT * FROM "s3://other-service.com/bucket-name/file.csv"

## PostgreSQL

Query any accessible PostgreSQL database

    SELECT * FROM "postgresql://username:password@example.com/database#table"

If you use query parameters, they will be used in the WHERE clause of the SELECT statement used to query the database.

## Mysql

Query any accessible MySQL database

    SELECT * FROM "mysql://username:password@example.com/database#table"

## FTP

Query files (in supported data formats) located on ftp servers

    SELECT * FROM "ftp://username:password@example.com/file.csv"
