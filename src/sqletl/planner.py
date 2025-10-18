from . import ast
from . import pipeline
from .errors import PlannerError


AGGREGATE_FUNCS = ("COUNT", "SUM", "AVG", "MIN", "MAX", "TOTAL", "GROUP_CONCAT", "STRING_AGG")


def plan(node):
    if isinstance(node, ast.Select):
        tasks = walk_select(node)
    elif isinstance(node, ast.With):
        tasks = walk_with(node)
    else:
        raise Exception(f"Unknown statement")
    return pipeline.Pipeline(tasks)


def walk_with(node):
    tasks = []
    for name, query in node.tables.items():
        tasks.append(pipeline.Table(name, walk_select(query)))
    tasks.extend(walk_select(node.select))
    return tasks


def walk_select(select):
    tasks = []
    queries = {}
    filters = None
        
    if len(select.from_) > 1:
        raise PlannerError("Multiple sources in FROM clause are not supported, use JOIN instead")

    # first with process the WHERE clause into a list of queries and filters
    # WHERE clause can contain query params mixed in bool expressions
    # ?param1 OR ?param2 will need 2 queries to be resolved
    if select.where:
        queries, filters = extract_bool_expr_queries(select.where)

    # using the FROM clause we build an ordered list of queries to perform
    sources = []
    for node in select.from_:
        if isinstance(node, ast.Join):
            joins = []
            left = walk_join(node, joins)
            sources.append(list(split_identifier(left)) + [None, None])
            sources.extend(reversed(joins))
        else:
            sources.append(list(split_identifier(node)) + [None, None])
    
    if None in queries and len([s for s in sources if not s[0]]) > 1:
        raise PlannerError("Cannot use multiple unaliased sources in FROM clause when using unidentified query params")

    cleanup_fields = []
    for alias, source, database, source_filters, join_type in sources:
        if source_filters and join_type not in ("INNER", "LEFT"):
            raise PlannerError(f"Unsupported JOIN type {join_type}")
        table_tasks = []
        source_queries = None
        source_params = []

        if source_filters:
            # this is a joint source
            # we also resolve its ON condition to potentially mutliple queries (same as WHERE)
            source_queries, source_filters = extract_bool_expr_queries(source_filters)
            if len(source_filters.nodes) > 1:
                raise PlannerError("OR expressions in JOIN's ON conditions are not supported")
            
        if source_queries and len(list(source_queries.values())[0]) > 1:
            raise PlannerError("OR expressions in JOIN's ON conditions are not supported")
        elif source_queries:
            # only one query is allowd in the ON clause, retrieve its params
            source_params = list(source_queries.values())[0][0]
    
        has_query_fields = source_params or queries.get(alias)
        if alias in queries:
            # the WHERE clause contains queries for this source
            for params in queries[alias]:
                table_tasks.append(create_source(source, params + source_params, database, cleanup_fields))
        else:
            table_tasks.append(create_source(source, source_params, database, cleanup_fields))
        
        if len(table_tasks) > 1:
            table_tasks = [pipeline.Union(*table_tasks)]
        else:
            table_tasks = table_tasks[0]
        table = pipeline.Alias(alias or source, table_tasks)
        if source_filters and source_filters.nodes:
            source_filters = walk_comparisons(source_filters.nodes[0].nodes, remove_query_fields=True)
            tasks.append(pipeline.Join([table], source_filters, left=join_type == "LEFT", preload=not has_query_fields))
        else:
            tasks.append(table)

    # we now process the SELECT clause
    fields = []
    expands = []
    mapping_append = False
    has_select = False
    has_aggregates = False
    for field in select.fields:
        alias = None
        if field == "*":
            mapping_append = True
            continue
        if isinstance(field, ast.Alias):
            alias = field.alias
            field = field.node
        if isinstance(field, ast.Function):
            if field.func == "EXPAND":
                args = [pipeline.Field(field.args[0].path)] + [a.value for a in field.args[1:]]
                expands.append(pipeline.Expand(*args))
                field = field.args[0]
            elif field.func == "UNNEST":
                args = [pipeline.Field(field.args[0].path)]
                expands.append(pipeline.Unnest(*args))
                field = field.args[0]
            elif field.func in AGGREGATE_FUNCS:
                has_aggregates = True
                has_select = True
            else:
                has_select = True
        elif isinstance(field, ast.Scalar) and not alias:
            has_select = True
        elif not isinstance(field, (ast.Field, ast.Scalar)):
            has_select = True
        if alias:
            field = ast.Alias(alias, field)
        fields.append(field)
            
    if (has_aggregates or select.group_by) and expands:
        raise PlannerError("Aggregates and EXPAND/UNNEST functions are not supported together")
    if select.window and expands:
        raise PlannerError("Windows and EXPAND/UNNEST functions are not supported together")

    if filters:
        filters = discard_filter_query_fields(filters)
    
    has_where = filters and (len(filters.nodes) > 1 or any([not isinstance(n, ast.Condition) or n.operator not in pipeline.Condition.operators\
                                                            for _and in filters.nodes for n in _and.nodes]))
    require_sql = has_select or has_where or select.group_by or select.window or not sources
    if require_sql:
        # the query contains pieces that need to be processed using a real SQL engine
        # we partially rebuild the SQL statement
        if mapping_append:
            fields.insert(0, ast.Field("*"))
        sql = ast.Select(prepare_fields_for_pipeline_sql(fields),
                         from_=[ast.Table("data")] if sources else None,
                         where=walk_filters(filters) if filters else None)
        if not expands:
            sql.group_by = select.group_by
            sql.window = select.window
            sql.distinct = select.distinct
            sql.order_by = select.order_by
            sql.limit = select.limit
            sql.offset = select.offset
        tasks.append(pipeline.SQL(str(sql), ignore_prev=not sources))
    else:
        if filters and filters.nodes:
            tasks.append(walk_comparisons(filters.nodes[0].nodes))
        if fields:
            mapping = {}
            if select.order_by:
                mapping.update({f.path: pipeline.Field(f.path, f.source) for f, d in select.order_by})
            for field in fields:
                alias, field = split_alias(field)
                field = convert_operand(field)
                mapping[alias or field.name] = field
            tasks.append(pipeline.Map(mapping, append=mapping_append))
    
    if (not fields or mapping_append) and cleanup_fields:
        tasks.append(pipeline.RemoveFields(cleanup_fields))

    if expands:
        tasks.extend(expands)
    
    if require_sql and expands:
        sql = ast.Select([], from_=[ast.Table("data")])
        sql.group_by = select.group_by
        sql.window = select.window
        sql.distinct = select.distinct
        sql.order_by = select.order_by
        sql.limit = select.limit
        sql.offset = select.offset
        tasks.append(pipeline.SQL(str(sql)))
    elif not require_sql:
        if select.distinct:
            tasks.append(pipeline.Distinct())
        if select.order_by:
            tasks.append(pipeline.Sort([(pipeline.Field(field.path, field.source), d) for field, d in select.order_by]))
        if select.limit:
            tasks.append(pipeline.Limit(int(select.limit), int(select.offset) if select.offset else None))
        elif select.offset:
            tasks.append(pipeline.Limit(None, int(select.offset)))

    return tasks
            

def create_source(source, params, database, cleanup_fields):
    tasks = [pipeline.Load(source, params, database)]
    if params:
        params = [(f"?{name}", pipeline.JointField(value) if isinstance(value, pipeline.Field) else value) for name, value in params]
        tasks.append(pipeline.Map(dict(params), append=True))
        cleanup_fields.extend([f[0] for f in params])
    return tasks
       

def walk_join(node, sources):
    if isinstance(node.right, ast.Join):
        left = walk_join(node.right, sources)
        sources.insert(0, list(split_identifier(left)) + [node.on, node.type])
    else:
        sources.insert(0, list(split_identifier(node.right)) + [node.on, node.type])
    return node.left


def discard_filter_query_fields(or_node):
    if len(or_node.nodes) > 1:
        return or_node
    _or = {}
    for _and in or_node.nodes:
        nodes = []
        for node in _and.nodes:
            if isinstance(node, ast.Condition) and isinstance(node.left, ast.QueryField):
                continue
            nodes.append(node)
        if nodes:
            _and = ast.And(nodes)
            _or[str(_and)] = _and
    if not _or:
        return None
    return ast.Or(list(_or.values()))


def prepare_fields_for_pipeline_sql(fields):
    out = []
    for field in fields:
        alias = None
        if isinstance(field, ast.Alias):
            alias = field.alias
            field = field.node
        if isinstance(field, ast.Field):
            field = ast.Field(field.path)
        out.append(ast.Alias(alias, field) if alias else field)
    return out


def walk_filters(or_node):
    for _and in or_node.nodes:
        for node in _and.nodes:
            if isinstance(node, ast.Condition) and isinstance(node.left, ast.QueryField):
                node.left = ast.Field(f"{node.left.source}__?{node.left.path}" if node.left.source else f"?{node.left.path}")
            elif isinstance(node, ast.Condition) and isinstance(node.left, ast.Field):
                node.left = ast.Field(f"{node.left.source}__{node.left.path}" if node.left.source else node.left.path)
    return or_node
        
    
def walk_comparisons(comparisons, remove_query_fields=False):
    out = pipeline.Filter([])
    for comp in comparisons:
        if remove_query_fields and isinstance(comp.left, ast.QueryField):
            continue
        out.conditions.append(
            pipeline.Condition(convert_operand(comp.left), comp.operator, convert_operand(comp.right))
        )
    if not out.conditions:
        return
    return out

        
def split_alias(node):
    if isinstance(node, ast.Alias):
        return node.alias, node.node
    return None, node


def split_identifier(node):
    alias, node = split_alias(node)
    return alias, node.url if isinstance(node, ast.URL) else node.name, node.database
            

def expand_bool_expr(node):
    """Expand (in the mathematical sense) a boolean expression
    Example: a AND (b OR c) => (a AND b) OR (a AND c)
    """
    if not isinstance(node, (ast.And, ast.Or)):
        return ast.Or([ast.And([node])])
    if isinstance(node, ast.Or):
        o = []
        for n in node.nodes:
            o.extend(expand_bool_expr(n).nodes)
        return ast.Or(o)
    _or = ast.Or([])
    for node in node.nodes:
        if isinstance(node, (ast.And, ast.Or)):
            o = ast.Or([])
            for _and in expand_bool_expr(node).nodes:
                for _and2 in _or.nodes:
                    _and.nodes = _and2.nodes + _and.nodes
                o.nodes.append(_and)
            _or = o
        elif not _or.nodes:
            _or.nodes.append(ast.And([node]))
        else:
            for _and in _or.nodes:
                _and.nodes.append(node)
    return _or


def extract_bool_expr_queries(node):
    bool_expr = expand_bool_expr(node)
    queries = {}
    max_queries = 0
    for _and in bool_expr.nodes:
        _params = {}
        for node in _and.nodes:
            if isinstance(node, ast.Condition) and isinstance(node.left, ast.QueryField):
                _params.setdefault(node.left.source, []).append((node.left.path, convert_operand(node.right)))
        for source, p in _params.items():
            queries.setdefault(source, []).append(p)
            max_queries = max([max_queries, len(queries[source])])
    for source, params in queries.items():
        if len(params) < max_queries:
            queries[source].append([])
    return queries, bool_expr


def convert_operand(field):
    if isinstance(field, ast.QueryField):
        return pipeline.Field(f"?{field.path}", field.source)
    if isinstance(field, ast.Field):
        return pipeline.Field(field.path, field.source)
    if isinstance(field, ast.Scalar):
        return field.value
    if isinstance(field, ast.Function):
        return pipeline.Expression(field.func, [convert_operand(a) for a in field.args])