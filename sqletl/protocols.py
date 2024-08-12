from .reader import read_file
from .datatable import DataTable
from io import BytesIO
import requests
import os
import urllib.parse
import psycopg
import mysql.connector
import s3fs


class Http:
    def get(self, ctx, url, params, content_type):
        fragment = None
        if "#" in url:
            url, fragment = url.split("#", 1)
        r = self.request(ctx, url, params)
        fd, response_content_type = self.process_response(r)
        return read_file(fd, url, fragment, content_type or response_content_type)
    
    def request(self, ctx, url, params, **kwargs):
        r = requests.get(url, params=params, **kwargs)
        r.raise_for_status()
        return r
    
    def process_response(self, response):
        content_type = None
        if "content-type" in response.headers:
            content_type = response.headers["content-type"].split(";")[0].strip()
        return BytesIO(response.content), content_type


class File:
    def __init__(self, path):
        self.path = os.path.abspath(path)

    def get(self, ctx, url, params, content_type):
        fragment = None
        if "#" in url:
            url, fragment = url.split("#", 1)
        filename = self.validate_filename(url[7:])
        with open(filename, 'r') as f:
            return read_file(f, filename, fragment, content_type)
        
    def validate_filename(self, filename):
        filename = os.path.abspath(os.path.join(self.path, filename))
        if not filename.startswith(self.path):
            raise Exception(f"Invalid path: {filename}")
        if not os.path.exists(filename):
            raise Exception(f"File not found: {filename}")
        return filename


class FsspecBase:
    def get(self, ctx, url, params, content_type):
        fragment = None
        if "#" in url:
            url, fragment = url.split("#", 1)
        fs, path = self.create_fs(url)
        with fs.open(path, 'rt') as f:
            return read_file(f, url, fragment, content_type)
        
    def create_fs(self, url):
        raise NotImplementedError()

    def parse_url(self, url):
        return urllib.parse.urlparse(url)


class Fsspec(FsspecBase):
    def __init__(self, protocol, strip_leading_slash=False):
        self.protocol = protocol
        self.strip_leading_slash = strip_leading_slash

    def create_fs(self, url):
        parts = self.parse_url(url)
        kwargs = {}
        if parts.username and parts.password:
            kwargs = {"username": parts.username, "password": parts.password}
        if parts.hostname:
            kwargs["host"] = parts.hostname
        if parts.port:
            kwargs["port"] = parts.port
        fs = fsspec.filesystem(self.protocol, **kwargs)
        path = parts.path[1:] if self.strip_leading_slash else parts.path
        return fs, path


class S3(FsspecBase):
    def create_fs(self, url):
        parts = self.parse_url(url)
        if parts.username and parts.password:
            kwargs = {"key": parts.username, "secret": parts.password}
        elif parts.username:
            kwargs = {"token": parts.username}
        else:
            kwargs = {"anon": True}
        if parts.hostname:
            kwargs["endpoint_url"] = f"https://{parts.hostname}"
        if parts.query:
            kwargs["client_kwargs"] = urllib.parse.parse_qs(parts.query)
        return s3fs.S3FileSystem(**kwargs), parts.path[1:]

    
class SQLProtocolBase:
    def get(self, ctx, url, params, content_type):
        url, stmt, values = self.build_query_info(url, params)
        conn = self.connect(url)
        dt = self.execute_query(conn, stmt, values)
        conn.close()
        return dt
            
    def build_query_info(self, url, params):
        fragment = None
        if "#" not in url:
            raise Exception("Missing table name (as url fragment)")
        url, table = url.split("#", 1)
        stmt = f"SELECT * FROM {table}"
        values = tuple()
        if params:
            conditions = [f'"{k}" = %s' for k in params]
            stmt += " WHERE " + " AND ".join(conditions)
            values = tuple(params.values())
        return url, stmt, values

    def connect(self, url):
        raise NotImplementedError()
            
    def execute_query(self, conn, stmt, values):
        cur = conn.cursor()
        cur.execute(stmt, values)
        cols = list([d[0] for d in cur.description])
        rows = cur.fetchall()
        cur.close()
        return DataTable(cols, rows)


class Postgresql(SQLProtocolBase):
    def connect(self, url):
        print(url)
        return psycopg.connect(url)


class Mysql(SQLProtocolBase):
    def connect(self, url):
        parts = urllib.parse.urlparse(url)
        return mysql.connector.connect(
            host=parts.hostname,
            port=parts.port or 3306,
            user=parts.username,
            password=parts.password,
            database=parts.path[1:],
        )


def default_procotols():
    return {
        'http': Http(),
        'https': Http(),
        'file': File(os.getcwd()),
        'ftp': Fsspec("ftp"),
        's3': S3(),
        'postgresql': Postgresql(),
        'mysql': Mysql(),
    }