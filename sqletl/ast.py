
class Node:
    def __eq__(self, other):
        return other.__class__ == self.__class__ and other.__dict__ == self.__dict__
    
    def __str__(self):
        return f"{self.__class__.__name__}({as_str(self.__dict__)})"


class Union(Node):
    def __init__(self, selects):
        self.selects = selects


class Intersect(Node):
    def __init__(self, selects):
        self.selects = selects


class Select(Node):
    def __init__(self, fields, from_=None, where=None, order_by=None, distinct=False, limit=None, offset=None):
        self.fields = fields
        self.from_ = from_ or []
        self.where = where
        self.order_by = order_by
        self.distinct = distinct
        self.limit = limit
        self.offset = offset


class Field(Node):
    def __init__(self, path, source=None):
        self.path = path
        self.source = source


class QueryField(Field):
    pass


class Alias(Node):
    def __init__(self, alias, node):
        self.alias = alias
        self.node = node


class URL(Node):
    def __init__(self, url):
        self.url = url


class Join(Node):
    def __init__(self, left, right, on, type="INNER"):
        self.left = left
        self.right = right
        self.on = on
        self.type = type


class Condition(Node):
    def __init__(self, left, operator, right):
        self.left = left
        self.operator = operator
        self.right = right


class And(Node):
    def __init__(self, nodes):
        self.nodes = nodes


class Or(Node):
    def __init__(self, nodes):
        self.nodes = nodes


class Not(Node):
    def __init__(self, node):
        self.node = node


class Scalar(Node):
    def __init__(self, value):
        self.value = value


class With(Node):
    def __init__(self, tables, select):
        self.tables = tables
        self.select = select


class Table(Node):
    def __init__(self, name):
        self.name = name


class Function(Node):
    def __init__(self, func, args):
        self.func = func
        self.args = args


def as_str(obj):
    if isinstance(obj, (list, tuple)):
        return [as_str(o) for o in obj]
    if isinstance(obj, dict):
        return {k: as_str(v) for k, v in obj.items()}
    return str(obj)