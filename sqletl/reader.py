from .datatable import DataTable, DictDataTable, iter_peek
from urllib.parse import parse_qsl
import json
import jsonpath_ng
import csv
import sqlite3
import tempfile
import os


def read_file(fd, filename=None, target_path=None, content_type=None):
    if not content_type and filename:
        content_type = guess_content_type_from_filename(filename)

    if content_type:
        if content_type not in READERS:
            raise Exception(f"Unsupported content type: {content_type}")
        return READERS[content_type](fd, target_path)
    
    for content_type, reader in READERS.items():
        try:
            return reader(fd, target_path)
        except:
            pass

    raise Exception("Failed to read file")


def read_json(fd, target_path=None):
    data = json.load(fd)
    if not data:
        return DataTable()
    return json_as_datatable(data, target_path)


def json_as_datatable(data, target_path=None):
    if target_path:
        expr = jsonpath_ng.parse(target_path)
        r = expr.find(data)
        if not r:
            return DataTable()
        data = r[0].value
    
    if isinstance(data, dict):
        return DictDataTable([data])
    return DictDataTable(data)


def read_csv(fd, target_path=None):
    params = {"header": "1", "delimiter": ",", "quote": '"'}
    if target_path:
        params.update({k: v[0] for k, v in parse_qsl(target_path)})
    r = csv.reader(fd, delimiter=params["delimiter"], quotechar=params["quote"])
    try:
        if "cols" in params:
            cols = params["cols"].split(",")
        elif params["header"] == "0":
            first, r = iter_peek(r)
            cols = [f"col{i}" for i in range(len(first))]
        else:
            cols = next(r)
        return DataTable(cols, list(r))
    except StopIteration:
        return DataTable()
    

def read_sqlite(fd, target_path=None):
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(fd.read())
    f.close()

    conn = sqlite3.connect(f.name)
    c = conn.cursor()
    c.execute('SELECT * FROM "%s"' % target_path)
    cols = [d[0] for d in c.description]
    dt = DataTable(cols, c.fetchall())
    c.close()
    conn.close()

    os.unlink(f.name)
    return dt


def guess_content_type_from_filename(filename):
    try:
        ext = filename.rsplit('.', 1)[-1]
        return CONTENT_TYPE_EXT_MAP.get(ext)
    except:
        return None


CONTENT_TYPE_EXT_MAP = {
    "json": "application/json",
    "csv": "text/csv",
    "sqlite": "application/x-sqlite3",
}

READERS = {
    "application/json": read_json,
    "text/csv": read_csv,
    "application/x-sqlite3": read_sqlite,
}
