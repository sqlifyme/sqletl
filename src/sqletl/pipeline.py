import jsonpath_ng
import statistics
import operator
from pprint import pprint
import textwrap
import sqlite3
import json
import itertools
import threading
import re
from contextlib import contextmanager
from .ctx import Context
from .datatable import DataTable, iter_peek
from .errors import PipelineError


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


class Group(Task):
    def __init__(self, tasks):
        super().__init__()
        self.tasks = TaskGroup(tasks)

    def run(self, ctx: Context, prev: DataTable):
        return self.tasks.run(ctx, prev)
    
    def __repr__(self):
        return f"{self.__class__.__name__}\n" + textwrap.indent(repr(self.tasks), "  ")


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
        try:
            value = dt.get(row, self.name, self.source)
        except:
            raise PipelineError("Unknown field: %s" % repr(self))
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


class Alias(Task):
    def __init__(self, name, tasks):
        self.name = name
        self.dependencies = [TaskGroup(tasks)]

    def _run(self, ctx: Context, prev: DataTable):
        dt = DataTable(prev.cols, prev)
        dt.set_source(self.name)
        return dt
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})\n" + textwrap.indent(repr(self.dependencies[0]), "  ")


class Table(Task):
    def __init__(self, name, tasks):
        self.name = name
        self.dependencies = [TaskGroup(tasks)]

    def _run(self, ctx: Context, prev: DataTable):
        ctx.create_table(self.name, prev)
        return DataTable()
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.name})\n" + textwrap.indent(repr(self.dependencies[0]), "  ")


class Load(Task):
    def __init__(self, uri, params=None, database=None, source=None):
        super().__init__()
        if isinstance(params, dict):
            params = list(params.items())
        self.uri = uri
        self.params = params or []
        self.database = database
        self.source = source

    def _run(self, ctx: Context, prev: DataTable):
        params = []
        row = None
        for k, v in self.params:
            if isinstance(v, (Field, Expression)):
                if row is None:
                    row = next(prev, [])
                params.append((k, v.resolve(prev, row)))
            else:
                params.append((k, v))
        dt = ctx.load(self.uri, params, self.database)
        if self.source:
            dt.set_source(self.source)
        return dt
    
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
    

def sql_like(value, expr):
    expr = expr.replace("%", ".*").replace("_", ".")
    return bool(re.match(expr, value))
        

class Condition:
    operators = {
        "=": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
        "like": sql_like
    }

    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right

    def match(self, dt, row):
        if isinstance(self.left, (Field, Expression)):
            left = self.left.resolve(dt, row)
        else:
            left = self.left

        if isinstance(self.right, (Field, Expression)):
            right = self.right.resolve(dt, row)
        else:
            right = self.right
    
        if self.op not in ("=", "!=") and left is None or right is None:
            return False

        return self.operators[self.op](left, right)
    
    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__
    
    def __repr__(self):
        return f"{self.left} {self.op.upper()} {self.right}"


class Expression:
    functions = ("concat", "lower", "upper")

    def __init__(self, func, args):
        self.func = func.lower()
        self.args = args

    def resolve(self, dt, row):
        args = [a.resolve(dt, row) if isinstance(a, (Field, Expression)) else a for a in self.args]
        try:
            return getattr(self, self.func)(*args)
        except:
            raise PipelineError(f"An error occured while running the expression '{self.func}'")

    def concat(self, *args):
        return "".join(args)
                
    def lower(self, s):
        return s.lower()
                    
    def upper(self, s):
        return s.upper()
    
    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__
    
    def __repr__(self):
        return f"{self.func}({', '.join(map(repr, self.args))})"


class Map(Task):
    def __init__(self, fields, source=None, append=False):
        super().__init__()
        self.fields = fields
        self.source = source
        self.append = append

    def _run(self, ctx: Context, prev: DataTable):
        def rows():
            for row in prev:
                _row = tuple(f.resolve(prev, row) if isinstance(f, Field) else f for f in self.fields.values())
                if self.append:
                    yield row + _row
                else:
                    yield _row
        cols = [(self.source, f) for f in self.fields.keys()]
        if self.append:
            cols = prev.cols + cols
        return DataTable(cols, rows())

    def __repr__(self):
        return f"Map({repr(self.fields)}, append={self.append})"


class RemoveFields(Task):
    def __init__(self, fields):
        super().__init__()
        self.fields = fields

    def _run(self, ctx: Context, prev: DataTable):
        idxes_to_remove = [prev.colidx(f.name, f.source) if isinstance(f, Field) else prev.colidx(f) for f in self.fields]
        def rows():
            for row in prev:
                yield tuple([row[i] for i in range(len(row)) if i not in idxes_to_remove])
        cols = [c for i, c in enumerate(prev.cols) if i not in idxes_to_remove]
        return DataTable(cols, rows())

    def __repr__(self):
        return f"RemoveColumns({self.fields})"


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
    def __init__(self, tasks, conditions=None, left=False, preload=False):
        super().__init__()
        self.tasks = TaskGroup(tasks)
        self.conditions = conditions if isinstance(conditions, Filter) else Filter(conditions) if conditions else None
        self.left = left
        self.preload = preload

    def _run(self, ctx: Context, prev: DataTable):
        joincols = None
        iterators= []
        preloaded_data = None

        if self.preload:
            dt = self.tasks.run(ctx, prev)
            if dt.is_empty():
                if not self.left:
                    return DataTable()
                return prev
            joincols = dt.cols
            preloaded_data = list(dt)
        
        for row in prev:
            with join_context((prev, row)):
                if self.preload:
                    related = DataTable(joincols, preloaded_data)
                else:
                    related = self.tasks.run(ctx, DataTable(prev.cols, [row]))
                
                if related.is_empty():
                    if not self.left:
                        continue
                    elif joincols:
                        related = [row + tuple([None] * len(joincols))]
                else:
                    if joincols is None:
                        joincols = related.cols
                    elif joincols != related.cols:
                        raise PipelineError("Incompatible columns")
                    related = [row + r for r in related]

                if self.conditions:
                    related = self.conditions._run(ctx, DataTable(prev.cols + joincols, list(related)))
                    iterators.append(related.rows)
                else:
                    iterators.append(list(related))

        return DataTable(prev.cols + joincols, itertools.chain.from_iterable(iterators))
    
    def __repr__(self):
        return f"{self.__class__.__name__}\n" + textwrap.indent(repr(self.tasks), "  ") + ("\n" + textwrap.indent(repr(self.conditions), "  ") if self.conditions else "")

            
class _JoinContext:
    """A per-thread stack of Session to keep track of the current session"""

    def __init__(self):
        self.locals = threading.local()

    @property
    def stack(self):
        if not hasattr(self.locals, "stack"):
            self.locals.stack = []
        return self.locals.stack

    @property
    def top(self):
        if self.stack:
            return self.stack[-1]

    def push(self, dt):
        self.stack.append(dt)

    def pop(self):
        self.stack.pop()

    @contextmanager
    def __call__(self, dt):
        self.push(dt)
        try:
            yield dt
        finally:
            self.pop()
    
    
join_context = _JoinContext()
        
    
class JointField(Field):
    def __init__(self, field):
        self.field = field

    def resolve(self, dt, row):
        return self.field.resolve(*join_context.top)

    def __repr__(self):
        return f"JointField({repr(self.field)})"
    
    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.field == other.field

                    
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
                if self.key_field:
                    _fields = {}
                    for k, v in fields.items():
                        v = self.key_field.find(v)
                        if v:
                            _fields[k] = v[0].value
                    fields = _fields
                    
            for f in fields:
                if f not in new_cols:
                    new_cols.append(f)
            row = list(row)
            row.pop(idx)
            yield tuple(row) + tuple(fields.get(f) for f in new_cols)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.field)})"
    

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
            if not isinstance(value, (list, dict)):
                raise PipelineError("UNNEST: Target field must be an array or object")
            row = list(row)
            row.pop(idx)
            row = tuple(row)

            if isinstance(value, dict):
                new_cols.extend(('key', 'value'))
                for k, v in value.items():
                    yield row + (k, v)
            else:
                for item in value:
                    if not isinstance(item, dict):
                        raise PipelineError("UNNEST: Array elements must be objects")
                    for f in item:
                        if f not in new_cols:
                            new_cols.append(f)
                    yield row + tuple(item.get(f) for f in new_cols)
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.field)})"


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
    def __init__(self, limit, offset=0):
        super().__init__()
        self.limit = limit
        self.offset = offset

    def _run(self, ctx: Context, prev: DataTable):
        return DataTable(prev, itertools.islice(prev, self.offset, self.limit))
    
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
        pprint((prev.cols, rows))
        return DataTable(prev.cols, rows)
    
    def __repr__(self):
        return "Print"
    

class SQL(Task):
    def __init__(self, query, source=None, ignore_prev=False):
        super().__init__()
        self.query = query
        self.source = source
        self.ignore_prev = ignore_prev

    def _run(self, ctx: Context, prev: DataTable):
        if not self.ignore_prev and prev.is_empty():
            return DataTable()
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        if not self.ignore_prev:
            cur.execute("CREATE TABLE data (%s)" % ', '.join([f'"{c}"' for c in prev.colnames]))
            cols = list(prev.idx_by_unique_names.values())
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


def unquote(string):
    for quote in ('"', "'"):
        if string.startswith(quote) and string.endswith(quote):
            return string[1:-1]
    return string


def sql_json_accessors_to_jsonpath(path):
    parts = path.replace("->>", "->").split("->")
    jsonpath = []
    for part in parts:
        part = unquote(part)
        if part.startswith("$"):
            jsonpath.append(part[1:])
        elif part.isdigit():
            jsonpath.append(f"[{part}]")
        else:
            jsonpath.append(part if part.startswith(".") else f".{part}")
    return "".join(jsonpath).lstrip(".")