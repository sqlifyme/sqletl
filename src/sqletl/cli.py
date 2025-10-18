from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from argparse import ArgumentParser
from .parser import parse
from .planner import plan


OUTPUT_FORMATS = {
    "csv": "to_csv",
    "sql": "to_sql",
    "xls": "to_excel",
    "json": "to_json",
    "html": "to_html",
    "parquet": "to_parquet",
    "md": "to_markdown"
}


parser = ArgumentParser()
parser.add_argument("statement", help="SQLETL statement to execute", nargs="*")
parser.add_argument("-e", "--explain", help="Explain the query plan", action='store_true')
parser.add_argument("-o", "--output", help=f"Output to file instead of stdout (supported formats: {', '.join(OUTPUT_FORMATS.keys())})")


def main():
    console = Console()
    args = parser.parse_args()

    stmt = " ".join(args.statement)
    if not stmt:
        stmt = Prompt.ask("Statement")

    try:
        ast = parse(stmt)
    except:
        console.print("Error parsing statement", style="bold red")
        return

    pipe = plan(ast)

    if args.explain:
        console.print(str(pipe))
        return

    dt = pipe.run()

    if args.output:
        ext = args.output.rsplit(".", 1)[1].lower()
        getattr(dt.to_dataframe(), OUTPUT_FORMATS[ext])(args.output)
        return

    table = Table(show_header=True, header_style="bold magenta")
    for col in dt.colnames:
        table.add_column(col)
    for row in dt:
        table.add_row(*map(str, row))

    console.print(table)