from .parser import parse
from .planner import plan


def execute(query, ctx=None):
    ast = parse(query)
    pipe = plan(ast)
    return pipe.run(ctx)