from .reader import read_file
from .datatable import DataTable, iter_peek
from io import BytesIO
import requests
import os
import urllib.parse
import psycopg
import mysql.connector
import s3fs
import fsspec
import json


class ProtocolError(Exception):
    pass


class Http:
    def get(self, ctx, url, params, content_type):
        return self.handle(ctx, "GET", url, params, content_type)
    
    def post(self, ctx, url, params, content_type):
        return self.handle(ctx, "POST", url, params, content_type)
    
    def handle(self, ctx, method, url, params, content_type):
        url, fragment, params = prepare_url(url, params)
        r = self.request(ctx, method, url, params)
        fd, response_content_type = self.process_response(r)
        return read_file(fd, url, fragment, content_type or response_content_type)
    
    def request(self, ctx, method, url, params, **kwargs):
        is_json_body = False
        if "?" in url:
            url = urllib.parse.urlparse(url)
            if url.query == "JSON":
                is_json_body = True
                url = url._replace(query=None)
            url = url.geturl()
        try:
            if is_json_body:
                kwargs["json"] = expand_params(params)
            elif method == "POST":
                kwargs["data"] = params
            else:
                kwargs["params"] = params
            print(kwargs)
            r = requests.request(method, url, **kwargs)
        except:
            raise ProtocolError(f"Request failed: {url}")
        raise_on_request_status(r)
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
        url, fragment, params = prepare_url(url, params)
        filename = self.validate_filename(url[7:])
        with open(filename, 'rb') as f:
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
        url, fragment, params = prepare_url(url, params)
        fs, path = self.create_fs(url, params)
        with fs.open(path, 'rb') as f:
            return read_file(f, url, fragment, content_type)
        
    def create_fs(self, url, params):
        raise NotImplementedError()

    def parse_url(self, url):
        return urllib.parse.urlparse(url)


class Fsspec(FsspecBase):
    def __init__(self, protocol, strip_leading_slash=False):
        self.protocol = protocol
        self.strip_leading_slash = strip_leading_slash

    def create_fs(self, url, params):
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
    def create_fs(self, url, params):
        parts = self.parse_url(url)
        if parts.username and parts.password:
            kwargs = {"key": parts.username, "secret": parts.password}
        elif parts.username:
            kwargs = {"token": parts.username}
        else:
            kwargs = {"anon": True}
        if parts.hostname:
            kwargs["endpoint_url"] = f"https://{parts.hostname}"
        if params:
            kwargs["client_kwargs"] = params
        return s3fs.S3FileSystem(**kwargs), parts.path[1:]

    
class SQLProtocolBase:
    def get(self, ctx, url, params, content_type):
        url, stmt, values = self.build_query_info(url, params)
        conn = self.connect(url)
        dt = self.execute_query(conn, stmt, values)
        conn.close()
        return dt
            
    def build_query_info(self, url, params):
        url, table, params = prepare_url(url, params, merge_params=False, keep_params=True)
        if not table:
            raise Exception("Missing table name (as url fragment)")
        stmt = f'SELECT * FROM "{table}"'
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


class GoogleSheets:
    def get(self, ctx, url, params, content_type):
        url, fragment, config = prepare_url(url, params)
        parts = self.parse_url(url)
        if not parts.hostname:
            raise Exception("Missing spreadsheetId (gsheets://token@spreadsheetId/sheetId)")
        if not parts.username:
            raise Exception("Missing authorization token (gsheets://token@spreadsheetId/sheetId)")

        config = dict(config)
        params = []
        if parts.path:
            params.append(("includeGridData", "true"))
            if fragment:
                params.append(("ranges", fragment))
        else:
            params.append(("fields", "sheets.properties(sheetId,title)"))

        r = requests.get(f"https://sheets.googleapis.com/v4/spreadsheets/{parts._hostinfo[0]}",
                            params=params,
                            headers={"Authorization": f"Bearer {parts.username}"})
        raise_on_request_status(r)
        data = r.json()

        if not parts.path:
            return DataTable(["sheetId", "title"], [(s["properties"]["sheetId"], s["properties"]["title"]) for s in data["sheets"]])

        sheet_id = parts.path.strip('/')
        found = True
        for sheet in data["sheets"]:
            if sheet["properties"]["sheetId"] == sheet_id:
                break
        if not found:
            raise Exception(f"Sheet not found: {sheet_id}")

        def iter_rows(sheet):
            for row in sheet["data"][0]["rowData"]:
                yield tuple(cell["formattedValue"] for cell in row["values"])

        rows = iter_rows(sheet)
        cols = []
        if config.get("colnames"):
            cols = next(rows)
        else:
            first_row, rows = iter_peek(rows)
            start = sheet["data"][0]["startColumn"] if "startColumn" in sheet["data"][0] else 0
            end = start + len(first_row)
            cols = [self.column_index_to_letter(i) for i in range(start+1, end+1)]

        return DataTable(cols, rows)
        
    def parse_url(self, url):
        return urllib.parse.urlparse(url)

    def column_index_to_letter(self, column):
        temp = letter = ""
        while column > 0:
            temp = (column - 1) % 26
            letter = chr(temp + 65) + letter
            column = (column - temp - 1) / 26
        return letter

        
def default_procotols():
    return {
        'http': Http(),
        'https': Http(),
        'file': File(os.getcwd()),
        'ftp': Fsspec("ftp"),
        's3': S3(),
        'postgresql': Postgresql(),
        'mysql': Mysql(),
        'gsheets': GoogleSheets()
    }


def prepare_url(url, params, merge_params=True, keep_params=False, url_params=True):
    url = urllib.parse.urlparse(url)
    fragment = url.fragment
    if merge_params and url.query:
        _params = dict(params)
        for key, value in urllib.parse.parse_qsl(url.query):
            if key not in _params:
                params.append((key, value))
        else:
            if url.query and not keep_params:
                keep_params = True
    if not keep_params:
        url = url._replace(query=None)
    url = url._replace(fragment=None).geturl()

    if url_params:
        _params = []
        for key, value in params:
            if ("{%s}" % key) in url:
                url = url.replace("{%s}" % key, value)
            else:
                _params.append((key, value))

    return url, fragment, _params


def raise_on_request_status(r):
    if not r.ok:
        if r.status_code in (401, 403):
            raise ProtocolError(f"Access denied: {r.url}\n{r.text}")
        if r.status_code == 404:
            raise ProtocolError(f"Resource not found: {r.url}\n{r.text}")
        if r.status_code == 400:
            raise ProtocolError(f"Bad request: {r.url}\n{r.text}")
        raise ProtocolError(f"Request failed: {r.url} ({r.status_code})\n{r.text}")


def expand_params(params):
    obj = None
    for key, value in params:
        parts = key.split('.')
        current = obj
        try:
            value = json.loads(value)
        except:
            pass
        for i, part in enumerate(parts):
            if part == "[]":
                if current is None:
                    current = obj = []
                elif isinstance(current, list):
                    current.append([])
                    current = current[-1]
                else:
                    raise Exception("Invalid key: %s" % key)
                continue
            if part.endswith("[]"):
                part = part[:-2]
                v = []
                if i == len(parts) - 1:
                    v.append(value)
            elif i == len(parts) - 1:
                v = value
            else:
                v = {}
            if isinstance(current, list):
                current.append({part: v})
                current = current[-1]
            elif current is None:
                current = obj = {part: v}
            else:
                current = current.setdefault(part, v)
    return obj