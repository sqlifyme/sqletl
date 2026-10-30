
class SqletlError(Exception):
    pass
    

class ContextError(SqletlError):
    pass


class PipelineError(SqletlError):
    pass


class PlannerError(SqletlError):
    pass


class ProtocolError(SqletlError):
    pass


class ReaderError(SqletlError):
    pass


class ParserError(SqletlError, SyntaxError):
    pass
