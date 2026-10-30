from lark import Lark, Transformer, UnexpectedInput, UnexpectedToken, v_args
import re
from . import ast
from .errors import ParserError


_parser = Lark.open("grammar.lark", rel_to=__file__, parser="lalr", propagate_positions=True,
                    maybe_placeholders=True)

BOOL_NODES = (ast.And, ast.Or, ast.Not, ast.Condition)


def parse(sql):
    try:
        tree = _parser.parse(sql)
    except UnexpectedToken as e:
        if e.token.type == "$END":
            raise ParserError("Invalid SQL: unexpected end of statement") from e
        raise ParserError(f"Invalid SQL at line {e.line}, column {e.column}:\n{e.get_context(sql)}") from e
    except UnexpectedInput as e:
        raise ParserError(f"Invalid SQL at line {e.line}, column {e.column}:\n{e.get_context(sql)}") from e
    return ToAST(sql).transform(tree)


def unquote(string, quote):
    return string[1:-1].replace(quote * 2, quote)


class ToAST(Transformer):
    def __init__(self, sql):
        super().__init__()
        self.sql = sql

    def raw(self, meta):
        return self.sql[meta.start_pos:meta.end_pos]

    def start(self, c):
        return c[0]

    def with_query(self, c):
        *ctes, select = c
        return ast.With(dict(ctes), select)

    def cte(self, c):
        return tuple(c)

    def select(self, c):
        distinct, fields, from_, where, group_by, window, order_by, limit = c
        limit, offset = limit or (None, None)
        return ast.Select(
            fields=fields,
            from_=from_,
            where=where,
            order_by=order_by,
            group_by=group_by,
            window=window,
            distinct=distinct is not None,
            limit=limit,
            offset=offset
        )

    def select_list(self, c):
        return c

    def star(self, c):
        return "*"

    def field(self, c):
        node, alias = c
        if isinstance(node, ast.QueryField):
            # "?param" in the SELECT clause refers to the column, not a query param
            node = ast.Field(f"?{node.path}", node.source)
        return ast.Alias(alias, node) if alias else node

    def alias(self, c):
        if getattr(c[0], "type", None) == "STRING":
            return unquote(c[0], "'")
        return c[0]

    # --- FROM

    def from_clause(self, c):
        return c

    def from_item(self, c):
        # a JOIN b ON x JOIN c ON y => Join(a, Join(b, c, y), x)
        tables = [c[0]] + [table for _, table, _ in c[1:]]
        node = tables[-1]
        for left, (type_, _, on) in reversed(list(zip(tables[:-1], c[1:]))):
            node = ast.Join(left, node, on, type_)
        return node

    def join(self, c):
        type_, table, on = c
        return (type_ or "INNER", table, on)

    def join_type(self, c):
        return c[0].upper()

    def table_ref(self, c):
        (name, schema), alias = c
        if re.match("[a-z]+://", name):
            source = ast.URL(name, schema)
        else:
            source = ast.Table(name, schema)
        return ast.Alias(alias, source) if alias else source

    def table_name(self, c):
        return (c[1], c[0]) if len(c) > 1 else (c[0], None)

    # --- other clauses

    def where_clause(self, c):
        return c[0]

    def group_by_clause(self, c):
        return c[0]

    def window_clause(self, c):
        return c[0]

    @v_args(meta=True)
    def group_by_body(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    @v_args(meta=True)
    def window_body(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    def order_by_clause(self, c):
        return c

    def order_item(self, c):
        field, direction = c
        return (field, direction.upper() if direction else "ASC")

    @v_args(meta=True)
    def order_expr(self, meta, c):
        node = c[0]
        if isinstance(node, ast.QueryField):
            return ast.Field(f"?{node.path}")
        if isinstance(node, ast.Field):
            return ast.Field(node.path)
        # expressions are referenced by their result column name
        return ast.Field(self.raw(meta))

    def limit_clause(self, c):
        return (str(c[0]), str(c[1]) if c[1] else None)

    def offset_clause(self, c):
        return (None, str(c[0]))

    # --- boolean expressions

    def or_expr(self, c):
        return ast.Or(c)

    def and_expr(self, c):
        return ast.And(c)

    def negation(self, c):
        return ast.Not(c[1])

    def comparison(self, c):
        left, op, right = c
        return ast.Condition(self.operand(left), op, self.operand(right))

    def comp_op(self, c):
        return " ".join(str(t).lower() for t in c if t is not None)

    def in_comparison(self, c):
        left, not_, values = c
        return ast.Condition(self.operand(left), "not in" if not_ else "in", values)

    def is_comparison(self, c):
        left, not_, right = c
        return ast.Condition(self.operand(left), "is not" if not_ else "is", self.operand(right))

    def operand(self, node):
        if isinstance(node, BOOL_NODES):
            return ast.SQLExpr(f"({node})")
        return node

    @v_args(meta=True)
    def in_values(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    @v_args(meta=True)
    def between(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    # --- value expressions

    @v_args(meta=True)
    def arith(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    @v_args(meta=True)
    def neg(self, meta, c):
        node = c[0]
        if isinstance(node, ast.Scalar) and type(node.value) in (int, float):
            return ast.Scalar(-node.value)
        return ast.SQLExpr(self.raw(meta))

    @v_args(meta=True)
    def paren(self, meta, c):
        # parentheses only group boolean expressions, anything else is kept as is
        if isinstance(c[0], BOOL_NODES):
            return c[0]
        return ast.SQLExpr(self.raw(meta))

    def string(self, c):
        return ast.Scalar(unquote(c[0], "'"))

    def number(self, c):
        if re.search("[.eE]", c[0]):
            return ast.Scalar(float(c[0]))
        return ast.Scalar(int(c[0]))

    def null(self, c):
        return ast.Scalar(None)

    def true(self, c):
        return ast.Scalar(True)

    def false(self, c):
        return ast.Scalar(False)

    def column(self, c):
        (name, source), *accessors = c
        path = name + "".join(accessors)
        if path.startswith("?"):
            return ast.QueryField(path[1:], source)
        return ast.Field(path, source)

    def column_name(self, c):
        return (c[1], c[0]) if len(c) > 1 else (c[0], None)

    def json_access(self, c):
        op, key = c
        if getattr(key, "type", None) == "STRING":
            key = unquote(key, "'")
        return f"{op}{key}"

    @v_args(meta=True)
    def func_expr(self, meta, c):
        func, filter_, over = c
        if over:
            return ast.WindowFunction(func, over, filter_)
        if filter_:
            return ast.SQLExpr(self.raw(meta))
        return func

    def func_call(self, c):
        name, args = c
        return ast.Function(name.upper(), args or [])

    def star_args(self, c):
        return [ast.Field("*")]

    def args(self, c):
        return c

    @v_args(meta=True)
    def distinct_arg(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    def filter_clause(self, c):
        return c[0]

    def over_clause(self, c):
        return c[0]

    @v_args(meta=True)
    def over_spec(self, meta, c):
        return self.raw(meta)

    @v_args(meta=True)
    def paren_group(self, meta, c):
        return self.raw(meta)

    @v_args(meta=True)
    def case_expr(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    @v_args(meta=True)
    def cast_expr(self, meta, c):
        return ast.SQLExpr(self.raw(meta))

    def identifier(self, c):
        if c[0].type == "QUOTED_NAME":
            return unquote(c[0], '"')
        return str(c[0])
