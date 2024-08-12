from . import ast
from . import pipeline


def plan(node):
    if isinstance(node, ast.Select):
        tasks = walk_select(node)
    elif isinstance(node, ast.With):
        tasks = walk_with(node)
    else:
        raise Exception(f"Unknown statement")
    return pipeline.Pipeline(tasks)


def walk_select(node):
    if not node.from_:
        froms = {None: ast.Table("__postgres__")}
    else:
        froms = walk_from(node.from_)

    tasks = []
    if node.where:
        tasks.extend(walk_condition(node.where, froms))
    elif isinstance(froms[None], list):
        tasks.extend(load_join(froms, None))
    else:
        tasks.extend(load_src(froms[None]))

    mapping = {}
    aggregs = {}
    expands = []
    for field in node.fields:
        alias = None
        if isinstance(field, ast.Alias):
            alias = field.alias
            field = field.node
        if isinstance(field, ast.Function):
            if not alias:
                alias = field.func.lower()
            if field.func == "EXPAND":
                args = [pipeline.Field(field.args[0].path, field.args[0].source)] + [a.value for a in field.args[1:]]
                mapping[args[0].name] = args[0]
                expands.append(pipeline.Expand(*args))
            elif field.func == "UNNEST":
                field = pipeline.Field(field.args[0].path, field.args[0].source)
                mapping[field.name] = field
                expands.append(pipeline.Unnest(field))
            elif field.func.lower() in pipeline.Aggregate.funcs:
                aggregs[alias] = [field.func.lower(), pipeline.Field(field.args[0].path, field.args[0].source)]
            else:
                raise Exception(f"Unknown function: {field.func}")
        else:
            if not alias:
                alias = field.path
            mapping[alias] = pipeline.Field(field.path, field.source)

    limit_task = None
    if node.limit:
        limit_task = pipeline.Limit(node.limit)

    if aggregs:
        tasks.append(pipeline.Aggregate(mapping, aggregs))
        if limit_task:
            tasks.append(limit_task)
    elif mapping:
        if limit_task:
            tasks.append(limit_task)
        tasks.append(pipeline.Map(mapping))
    if expands:
        tasks.extend(expands)

    if node.distinct:
        tasks.append(pipeline.Distinct())

    if node.order_by:
        tasks.append(pipeline.Sort([(pipeline.Field(field.path, field.source), d) for field, d in node.order_by]))

    return tasks


def walk_from(froms):
    out = {}
    for node in froms:
        if isinstance(node, ast.Join):
            tables = walk_join(node)
            if not out:
                out[None] = tables
            for alias, table, on in tables:
                out[alias] = tables
        else:
            alias, node = walk_source(node)
            if not out:
                out[None] = node
            out[alias] = node
    return out


def walk_source(node):
    alias = None
    if isinstance(node, ast.Alias):
        alias = node.alias
        node = node.node
    if not alias:
        if isinstance(node, ast.URL):
            alias = node.url
        else:
            alias = node.name
    return alias, node


def walk_join(node):
    if not isinstance(node, ast.Join):
        alias, node = walk_source(node)
        return [[alias, node, None]]
    alias, n = walk_source(node.left)
    tables = [[alias, n, None]]
    tables.extend(walk_join(node.right))
    tables[1][2] = node.on
    return tables


def walk_with(node):
    tasks = []
    for name, query in node.tables.items():
        tasks.append(pipeline.CreateTable(name, walk_select(query)))
    tasks.extend(walk_select(node.select))
    return tasks


def load_src(node, params=None, alias=None):
    if isinstance(node, ast.URL):
        tasks = [pipeline.Load(node.url, params)]
    else:
        tasks = [pipeline.Load(node.name, params)]
        if alias and alias == node.name:
            return tasks
    if alias:
        return [pipeline.Table(alias, tasks)]
    return tasks


def load_join(froms, src, queries=None, filters=None, ignore=None):
    queries = queries or {}
    tasks = []
    for alias, table, on in froms[src]:
        if ignore is not None:
            ignore.add(alias)
        _tasks = []
        if on:
            q, g, f = split_and(ast.And([on]), froms)
            if q:
                params = dict(queries.get(alias, {}), **q.popitem()[1])
            else:
                params = queries.get(alias, {})
            _tasks = [pipeline.Join(load_src(table, params, alias))]
            if filters and alias in filters:
                _tasks.append(pipeline.Filter(filters.pop(alias)))
            tasks.append(pipeline.Table(alias, _tasks))
        else:
            _tasks = load_src(table, queries.get(alias, {}), alias)
            if filters and alias in filters:
                _tasks.append(pipeline.Filter(filters.pop(alias)))
            tasks.extend(_tasks)
    return tasks


def walk_condition(condition, froms):
    if isinstance(condition, ast.Condition):
        return walk_condition(ast.And([condition]), froms)
    
    if isinstance(condition, ast.And):
        queries, groups, filters = split_and(condition, froms)

        ignore = set()
        for src, params in queries.items():
            if src in ignore:
                continue
            if isinstance(froms[src], list):
                groups.append(load_join(froms, src, queries, filters, ignore))
            else:
                groups.append(load_src(froms[src], params, src))

        if not groups:
            groups.append(load_src(froms[None]))

        if len(groups) > 1:
            tasks = [pipeline.Intersection(*groups)]
        else:
            tasks = groups[0]

        if filters:
            return tasks + [pipeline.Filter(filters.popitem()[1])]
        return tasks

    if isinstance(condition, ast.Or):
        groups = []
        for node in condition.nodes:
            if isinstance(condition, ast.Condition):
                p, f, j = split_condition(node)
                if p:
                    src, params = p.popitem()
                    groups.append(load_src(froms[src], params, src))
                else:
                    src, filters = f.popitem()
                    groups.append(
                        load_src(froms[src], alias=src) + [pipeline.Filter(filters)]
                    )
            else:
                groups.append(walk_condition(node, froms))
        if len(groups) > 1:
            return [pipeline.Union(*groups)]
        return groups[0]
    

def split_and(and_node, froms):
    queries = {}
    groups = []
    filters = {}
    for node in and_node.nodes:
        if isinstance(node, ast.Condition):
            p, f, j = split_condition(node)
            for k, v in p.items():
                queries.setdefault(k, {}).update(v)
            for k, v in f.items():
                filters.setdefault(k, []).extend(v)
        else:
            groups.append(walk_condition(node, froms))
    return queries, groups, filters


def split_condition(condition):
    params = {}
    filters = {}
    joins = {}
    if isinstance(condition.left, ast.QueryField):
        params.setdefault(condition.left.source, {})[condition.left.path] = convert_operand(condition.right)
    elif isinstance(condition.left, ast.Field):
        filters.setdefault(condition.left.source, []).append(
            pipeline.Condition(convert_operand(condition.left), condition.operator, convert_operand(condition.right)))
    else:
        filters.setdefault(condition.right.source, []).append(
            pipeline.Condition(convert_operand(condition.right), condition.operator, convert_operand(condition.left)))
    return [params, filters, joins]


def convert_operand(field):
    if isinstance(field, ast.Field):
        return pipeline.Field(field.path, field.source)
    if isinstance(field, ast.Scalar):
        return field.value
