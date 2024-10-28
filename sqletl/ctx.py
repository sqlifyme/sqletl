from .protocols import default_procotols
from .reader import guess_content_type_from_filename
from .errors import ContextError


class Context:
    def __init__(self, protocols=None):
        self.tables = {}
        self.protocols = protocols or default_procotols()
    
    def load(self, uri, params, database=None):
        method = "GET"
        if uri.startswith("POST "):
            method = "POST"
            uri = uri[5:]
        if "://" not in uri:
            if method != "GET":
                raise ContextError("Only GET method supported for tables")
            if params:
                raise ContextError("Parameters not supported for tables")
            return self.get_table(uri)
        scheme = uri.split("://")[0].lower()
        content_type = None
        if "+" in scheme:
            scheme, ext = scheme.split("+")
            content_type = guess_content_type_from_filename(ext)
        protocol = self.resolve_protocol(scheme)
        if not protocol:
            raise ContextError(f"Protocol {scheme} not supported")
        func = getattr(protocol, method.lower(), None)
        if not func:
            raise ContextError(f"Method GET not supported for protocol {scheme}")
        return func(self, uri, params, content_type)
    
    def resolve_protocol(self, scheme):
        return self.protocols.get(scheme)

    def create_table(self, name, dt):
        self.tables[name] = dt
    
    def get_table(self, name):
        if name not in self.tables:
            raise ContextError(f"Table {name} not found")
        return self.tables[name]

    def get_tables(self):
        return self.tables