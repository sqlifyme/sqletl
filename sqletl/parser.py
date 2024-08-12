from postgres_proto.sql import Parser as BaseParser
from postgres_proto.sql.tokenizer import unquote, split_sql, tokenize_list
import re
from . import ast


def parse(sql):
    return Parser().parse(sql)


class Parser(BaseParser):
    def parse(self, sql):
        stmt_type, node = super().parse(sql)
        if not isinstance(node, ast.Node):
            raise SyntaxError(f"Unsupported statement type: {stmt_type}")
        return node

    def parse_select(self, sql):
        info = super().parse_select(sql)
        return ast.Select(
            fields=info.columns,
            from_=info.tables,
            where=self.parse_where(info.where) if info.where else None,
            order_by=list(self.parse_order_by(info.order_by)) if info.order_by else None,
            distinct=info.distinct,
            limit=info.limit,
            offset=info.offset
        )

    def parse_select_cols(self, sql):
        for info in super().parse_select_cols(sql):
            if info.name == "*":
                yield None
                continue
            if re.match("[a-z0-9_]+\(", info.name, re.I):
                name, args = self.parse_sql_func(info.name)
                field = ast.Function(name.upper(), [self.parse_expr(e) for e in args])
            else:
                field = ast.Field(info.name, info.schema)
            if info.alias:
                yield ast.Alias(info.alias, field)
            else:
                yield field

    def parse_from_entry(self, table_expr):
        info = super().parse_from_entry(table_expr)
        return self.walk_from_entry(info)
    
    def walk_from_entry(self, info):
        if re.match("[a-z]+://", info.name):
            source = ast.URL(info.name)
        else:
            source = ast.Table(f'"{info.schema}"."{info.name}"' if info.schema else info.name)
        if info.alias:
            source = ast.Alias(info.alias, source)
        if info.join:
            on = self.parse_where(info.join.on)
            return ast.Join(source, self.walk_from_entry(info.join.table), on)
        return source
    
    def parse_where(self, sql):
        return self.parse_where_expr(sql)
    
    def parse_where_expr(self, sql):
        where = super().parse_where_expr(sql)
        if isinstance(where, dict) and "$and" in where:
            return ast.And(where["$and"])
        if isinstance(where, dict) and "$or" in where:
            return ast.Or(where["$or"])
        return where
        
    def parse_condition(self, sql):
        left, op, right = super().parse_condition(sql)
        return ast.Condition(self.parse_expr(left), op, self.parse_expr(right))
    
    def parse_expr(self, expr):
        if expr.startswith("'"):
            return ast.Scalar(unquote(expr))
        if re.match(r"^\d+$", expr):
            return ast.Scalar(int(expr))
        if re.match("[a-z0-9_]+\(", expr, re.I):
            name, args = self.parse_sql_func(expr)
            return ast.Function(name.upper(), [self.parse_expr(e) for e in args])
        name, schema, alias = self.parse_identifier(expr)
        if name.startswith("?"):
            return ast.QueryField(name[1:], schema)
        return ast.Field(name, schema)
    
    def parse_order_by(self, sql):
        for order, _ in tokenize_list(sql):
            if order.upper().endswith("DESC"):
                yield (ast.Field(*self.parse_identifier(order[:-4].strip())[:1]), "DESC")
            elif order.upper().endswith("ASC"):
                yield (ast.Field(*self.parse_identifier(order[:-4].strip())[:1]), "ASC")
            else:
                yield (ast.Field(*self.parse_identifier(order.strip())[:1]), "ASC")
    
    def parse_with(self, sql):
        parts = split_sql(sql, ('WITH', 'SELECT'))
        tables = {}
        for table_def, _ in tokenize_list(parts["WITH"]):
            name, select_stmt = [t[0] for t in tokenize_list(table_def, " AS ", remove_group_delimiters=True)]
            tables[unquote(name)] = self.parse_select(select_stmt)
        return ast.With(tables, self.parse_select("SELECT " + parts["SELECT"]))