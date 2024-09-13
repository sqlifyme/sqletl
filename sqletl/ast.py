
class Node:
    def __eq__(self, other):
        return other.__class__ == self.__class__ and other.__dict__ == self.__dict__
    
    def __repr__(self):
        return f"{self.__class__.__name__}({repr(self.__dict__)})"


class Union(Node):
    def __init__(self, selects):
        self.selects = selects

    def __str__(self):
        return " UNION ".join([str(s) for s in self.selects])


class Intersect(Node):
    def __init__(self, selects):
        self.selects = selects
    
    def __str__(self):
        return " INTERSECT ".join([str(s) for s in self.selects])


class Select(Node):
    def __init__(self, fields=None, from_=None, where=None, group_by=None, window=None, order_by=None, distinct=False, limit=None, offset=None):
        self.fields = fields or []
        self.from_ = from_ or []
        self.where = where
        self.order_by = order_by
        self.group_by = group_by
        self.window = window
        self.distinct = distinct
        self.limit = limit
        self.offset = offset

    def __str__(self):
        p = ["SELECT"]
        if self.distinct:
            p.append("DISTINCT")
        if self.fields:
            p.append(", ".join([str(f) for f in self.fields]))
        else:
            p.append("*")
        if self.from_:
            p.append("FROM")
            p.append(", ".join([str(f) for f in self.from_]))
        if self.where:
            p.append(f"WHERE {self.where}")
        if self.group_by:
            p.append(f"GROUP BY {self.group_by}")
        if self.window:
            p.append(f"WINDOW {self.window}")
        if self.order_by:
            p.append("ORDER BY")
            p.append(", ".join([f"{str(f)} {d}" for f, d in self.order_by]))
        if self.limit:
            p.append(f"LIMIT {self.limit}")
        if self.offset:
            p.append(f"OFFSET {self.offset}")
        return " ".join(p)


class Field(Node):
    def __init__(self, path, source=None):
        self.path = path
        self.source = source

    def __str__(self):
        if self.path == "*":
            return "*"
        if self.source:
            return f'"{self.source}"."{self.path}"'
        return f'"{self.path}"'


class QueryField(Field):
    def __str__(self):
        if self.source:
            return f'"{self.source}"."?{self.path}"'
        return f'"?{self.path}"'


class Alias(Node):
    def __init__(self, alias, node):
        self.alias = alias
        self.node = node

    def __str__(self):
        return f'{self.node} AS "{self.alias}"'


class URL(Node):
    def __init__(self, url, database=None):
        self.url = url
        self.database = database

    def __str__(self):
        if self.database:
            return f'"{self.database}"."{self.url}"'
        return f'"{self.url}"'


class Join(Node):
    def __init__(self, left, right, on, type="INNER"):
        self.left = left
        self.right = right
        self.on = on
        self.type = type
    
    def __str__(self):
        return f'{self.left} {self.type} JOIN {self.right} ON {self.on}'


class Condition(Node):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right

    def __str__(self):
        return f'{self.left} {self.operator} {self.right}'


class And(Node):
    def __init__(self, nodes):
        self.nodes = nodes

    def __str__(self):
        if len(self.nodes) == 1:
            return str(self.nodes[0])
        return "(" + " AND ".join([str(n) for n in self.nodes]) + ")"


class Or(Node):
    def __init__(self, nodes):
        self.nodes = nodes

    def __str__(self):
        if len(self.nodes) == 1:
            return str(self.nodes[0])
        return "(" + " OR ".join([str(n) for n in self.nodes]) + ")"

class Not(Node):
    def __init__(self, node):
        self.node = node

    def __str__(self):
        return f"NOT {self.node}"


class Scalar(Node):
    def __init__(self, value):
        self.value = value

    def __str__(self):
        if isinstance(self.value, str):
            return f"'{self.value}'"
        return str(self.value)


class With(Node):
    def __init__(self, tables, select):
        self.tables = tables
        self.select = select

    def __str__(self):
        return f"WITH {', '.join([f'{k} AS ({v})' for k, v in self.tables.items()])} {self.select}"


class Table(Node):
    def __init__(self, name, database=None):
        self.name = name
        self.database = database

    def __str__(self):
        if self.database:
            return f'"{self.database}"."{self.name}"'
        return f'"{self.name}"'


class Function(Node):
    def __init__(self, func, args):
        self.func = func
        self.args = args

    def __str__(self):
        return f"{self.func}({', '.join([str(a) for a in self.args])})"


class WindowFunction(Node):
    def __init__(self, func, over, filter=None):
        self.func = func
        self.over = over
        self.filter = filter

    def __str__(self):
        if self.filter:
            return f"{self.func} FILTER {self.filter} OVER {self.over}"
        return f"{self.func} OVER {self.over}"


class SQLExpr(Node):
    def __init__(self, sql):
        self.sql = sql

    def __str__(self):
        return self.sql