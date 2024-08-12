import jsonpath_ng
import statistics
import operator
from pprint import pprint
import textwrap
import sqlite3
import json
import itertools
from .ctx import Context
from .datatable import DataTable, iter_peek


class Task:
    def __init__(self):
        self.dependencies = []
    
    def run(self, ctx: Context, prev: DataTable):
        deps = [dep.run(ctx, prev) for dep in self.dependencies]
        if not deps:
            deps = [prev]
        return self.run_after_deps(ctx, deps)
    
    def run_after_deps(self, ctx: Context, deps):
        return self._run(ctx, deps[0])
    
    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, [self._each(ctx, row) for row in prev])

    def _each(self, ctx: Context, row: dict):
        raise NotImplementedError()

    def __repr__(self):
        return self.__class__.__name__

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__


class TaskGroup:
    def __init__(self, tasks=None):
        self.tasks = tasks or []

    def run(self, ctx, prev):
        for task in self.tasks:
            prev = task.run(ctx, prev)
        return prev
    
    def __iter__(self):
        return iter(self.tasks)
    
    def __repr__(self):
        return "\n".join([repr(t) for t in self.tasks])

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__


class Pipeline(TaskGroup):
    def add(self, task):
        self.tasks.append(task)

    def run(self, ctx: Context = None):
        if not ctx:
            ctx = Context()
        return super().run(ctx, DataTable())


class Field:
    def __init__(self, name, source=None, path=None):
        if "->" in name:
            name, sql_json_accessors = name.split("->", 1)
            path = sql_json_accessors_to_jsonpath(sql_json_accessors.lstrip(">"))
        self.name = name
        self.path = path
        self.source = source
        if path:
            self.expr = jsonpath_ng.parse(path)

    def resolve(self, dt, row):
        value = dt.get(row, self.name, self.source)
        if value and self.path:
            value = self.expr.find(value)
            if value:
                return value[0].value
            return None
        return value
    
    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.name == other.name and self.path == other.path and self.source == other.source
    
    def __getstate__(self):
        return self.name, self.path, self.source
    
    def __setstate__(self, state):
        self.name, self.path, self.source = state
        if self.path:
            self.expr = jsonpath_ng.parse(self.path)

    def __repr__(self):
        return "Field(%s)" % ((f"{self.source}.{self.name}" if self.source else self.name) + (f".{self.path}" if self.path else ""))


class Table(Task):
    def __init__(self, name, tasks):
        self.name = name
        self.dependencies = [TaskGroup(tasks)]

    def _run(self, ctx: Context, prev: DataTable):
        prev.rename_source(None, self.name)
        return prev
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})\n" + textwrap.indent(repr(self.dependencies[0]), "  ")


class CreateTable(Table):
    def _run(self, ctx: Context, prev: DataTable):
        ctx.create_table(self.name, super()._run(ctx, prev))
        return DataTable()


class Load(Task):
    def __init__(self, uri, params=None, source=None):
        super().__init__()
        self.uri = uri
        self.params = params or {}
        self.source = source or uri

    def _run(self, ctx: Context, prev: DataTable):
        params = {}
        row = None
        for k, v in self.params.items():
            if isinstance(v, Field):
                if row is None:
                    row = next(iter(prev), [])
                params[k] = v.resolve(prev, row)
            else:
                params[k] = v
        return ctx.load(self.uri, params)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.uri}, {repr(self.params)})"


class Filter(Task):
    def __init__(self, conditions):
        super().__init__()
        if isinstance(conditions, dict):
            self.conditions = [Condition(Field(k), "=", v) for k, v in conditions.items()]
        else:
            self.conditions = conditions

    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, [row for row in prev if all([c.match(prev, row) for c in self.conditions])])
    
    def __repr__(self):
        return f"Filter({' AND '.join(map(repr, self.conditions))})"
    

class Condition:
    operators = {
        "=": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le
    }

    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

    def match(self, dt, row):
        if isinstance(self.left, Field):
            left = self.left.resolve(dt, row)
        else:
            left = self.left

        if isinstance(self.right, Field):
            right = self.right.resolve(dt, row)
        else:
            right = self.right
    
        if self.op not in ("=", "!=") and left is None or right is None:
            return False

        return self.operators[self.op](left, right)
    
    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__
    
    def __repr__(self):
        return f"{self.left} {self.op} {self.right}"


class Map(Task):
    def __init__(self, fields, source=None):
        super().__init__()
        self.fields = {k: f if isinstance(f, Field) else Field(f) for k, f in fields.items()}
        self.source = source

    def _run(self, ctx: Context, prev: DataTable):
        rows = [tuple(f.resolve(prev, row) for f in self.fields.values()) for row in prev]
        return DataTable(self.fields.keys(), rows, self.source)

    def __repr__(self):
        return f"Map({repr(self.fields)})"


class Intersection(Task):
    def __init__(self, *groups):
        self.dependencies = [TaskGroup(tasks) for tasks in groups]

    def run_after_deps(self, ctx: Context, deps):
        groups = []
        cols = None
        for dt in deps:
            if cols is None:
                cols = dt.cols
            elif cols != dt.cols:
                raise ValueError("Incompatible columns")
            groups.append(set(dt))
        out = groups[0]
        for group in groups[1:]:
            out = out.intersection(group)
        return DataTable(cols, out)
    
    def __repr__(self):
        out = "Intersection\n"
        for group in self.dependencies:
            s = textwrap.indent(repr(group), "    ")
            out += "  - " + s[4:]
        return out


class Union(Task):
    def __init__(self, *groups):
        self.dependencies = [TaskGroup(tasks) for tasks in groups]

    def run_after_deps(self, ctx: Context, deps):
        cols = None
        iterators = []
        for dt in deps:
            if cols is None:
                cols = dt.cols
            elif cols != dt.cols:
                raise ValueError("Incompatible columns")
            iterators.append(iter(dt))
        return DataTable(cols, itertools.chain.from_iterable(iterators))
    
    def __repr__(self):
        out = "Union"
        for group in self.dependencies:
            s = textwrap.indent(repr(group), "    ")
            out += "\n  - " + s[4:]
        return out


class Join(Task):
    def __init__(self, tasks, left=False):
        super().__init__()
        self.tasks = TaskGroup(tasks)
        self.left = left

    def _run(self, ctx: Context, prev: DataTable):
        joincols = None
        iterators= []
        for row in prev:
            related = self.tasks.run(ctx, DataTable(prev.cols, [row]))
            if joincols is None:
                joincols = related.cols
            elif joincols != related.cols:
                raise ValueError("Incompatible columns")
            
            if related.is_empty():
                if self.left:
                    iterators.append([row + tuple([None] * len(joincols))])
            else:
                iterators.append([row + r for r in related])
        return DataTable(prev.cols + joincols, itertools.chain.from_iterable(iterators))
    
    def __repr__(self):
        return f"{self.__class__.__name__}\n" + textwrap.indent(repr(self.tasks), "  ")
    

class Expand(Task):
    def __init__(self, field, key_field=None, value_field=None, source=None):
        super().__init__()
        self.field = field if isinstance(field, Field) else Field(field)
        self.key_field = jsonpath_ng.parse(key_field) if key_field else None
        self.value_field = jsonpath_ng.parse(value_field) if value_field else None
        self.source = source or self.field.source

    def _run(self, ctx: Context, prev: DataTable):
        rows = []
        new_cols = []
        idx = prev.colidx(self.field.name, self.field.source)
        rows = list(self.expand(prev, new_cols, idx))
        cols = list(prev.cols)
        cols.pop(idx)
        return DataTable(cols + [(self.source, c) for c in new_cols], rows)
    
    def expand(self, prev, new_cols, idx):
        for row in prev:
            value = row[idx]
            fields = {}
            if isinstance(value, list):
                for item in value:
                    k = self.key_field.find(item)
                    if k:
                        v = self.value_field.find(item)
                        if v:
                            fields[k[0].value] = v[0].value
            else:
                fields = value
            for f in fields:
                if f not in new_cols:
                    new_cols.append(f)
            row = list(row)
            row.pop(idx)
            yield tuple(row) + tuple(fields.get(f) for f in new_cols)
    

class Unnest(Task):
    def __init__(self, field, source=None):
        super().__init__()
        self.field = field if isinstance(field, Field) else Field(field)
        self.source = source or self.field.source

    def _run(self, ctx: Context, prev: DataTable):
        rows = []
        new_cols = []
        idx = prev.colidx(self.field.name, self.field.source)
        rows = list(self.unnest(prev, new_cols, idx))
        cols = list(prev.cols)
        cols.pop(idx)
        return DataTable(cols + [(self.source, c) for c in new_cols], rows)
    
    def unnest(self, prev, new_cols, idx):
        for row in prev:
            value = row[idx]
            if not isinstance(value, list):
                raise Exception()
            row = list(row)
            row.pop(idx)
            row = tuple(row)
            
            for item in value:
                if not isinstance(item, dict):
                    raise Exception()
                for f in item:
                    if f not in new_cols:
                        new_cols.append(f)
                yield row + tuple(item.get(f) for f in new_cols)


class Aggregate(Task):
    funcs = {
        "count": len,
        "sum": sum,
        "avg": statistics.mean,
        "median": statistics.median
    }

    def __init__(self, dimensions, aggregates, source=None):
        super().__init__()
        self.dimensions = dimensions
        self.aggregates = aggregates
        self.source = source

    def _run(self, ctx: Context, prev: DataTable):
        dimensions = {tuple(): prev}
        if self.dimensions:
            dimensions = {}
            for row in prev:
                values = tuple([field.resolve(prev, row) for field in self.dimensions.values()])
                dimensions.setdefault(values, []).append(row)

        cols = list(self.dimensions.keys()) + list(self.aggregates.keys())
        def it():
            for key, rows in dimensions.items():
                row = list(key)
                for aggreg in self.aggregates.values():
                    values = filter(lambda v: v is not None, [aggreg[1].resolve(prev, r) for r in rows])
                    row.append(self.funcs[aggreg[0]](values))
                yield tuple(row)
        return DataTable(cols, it(), self.source)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.dimensions)}, {repr(self.aggregates)})"
    

class Sort(Task):
    def __init__(self, fields):
        super().__init__()
        self.fields = fields

    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, sorted(prev, key=lambda r: self.fields[0][0].resolve(prev, r), reverse=self.fields[0][1] == "DESC"))
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.fields)})"
    

class Limit(Task):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, itertools.islice(prev, self.limit))
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.limit})"
    

class Distinct(Task):
    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, set(prev))
    
    def __repr__(self):
        return f"{self.__class__.__name__}"


class Print(Task):
    def _run(self, ctx, prev):
        rows = list(prev)
        pprint(rows)
        return DataTable(prev, rows)
    
    def __repr__(self):
        return "Print"
    

class SQL(Task):
    def __init__(self, query, source=None):
        super().__init__()
        self.query = query
        self.source = source

    def _run(self, ctx: Context, prev: DataTable):
        if prev.is_empty():
            return DataTable()
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        cur.execute("CREATE TABLE data (%s)" % ', '.join(prev.prefixed_cols))
        cols = list(range(len(prev.cols)))
        bindings = [[json.dumps(row[i]) if isinstance(row[i], (list, dict)) else row[i] for i in cols] for row in prev]
        cur.executemany(f"INSERT INTO data VALUES ({', '.join(['?' for _ in prev.cols])})", bindings)
        cur.execute(self.query)
        rows = cur.fetchall()
        cols = [col[0] for col in cur.description]
        cur.close()
        conn.close()
        return DataTable(cols, rows, self.source)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.query})"


def sql_json_accessors_to_jsonpath(path):
    parts = path.replace("->>", "->").split("->")
    jsonpath = []
    for part in parts:
        if part.isdigit():
            jsonpath.append(f"[{part}]")
        else:
            jsonpath.append(f".{part}")
    return "".join(jsonpath).lstrip(".")