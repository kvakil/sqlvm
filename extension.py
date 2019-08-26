from jinja2 import nodes, TemplateSyntaxError, Environment
from jinja2.ext import Extension
from jinja2.lexer import Token


def fail_template(stream, message):
    raise TemplateSyntaxError(
        message, stream.current.lineno, stream.name, stream.filename
    )


class SqlvmExtension(Extension):
    """The SqlvmExtension wraps the containing Jinja2 templates in
    order to evaluate (some of them) as SQLVM templates.
    
    It also adds calls to evaluate the template functions {{prologue}},
    {{statement}} and {{epilogue}} wherever appropriate (see filter_stream).
    Dialects can then hook into these functions for bookkeeping."""

    tags = {"sqlvm"}

    def __init__(self, environment):
        super(SqlvmExtension, self).__init__(environment)

    def parse(self, parser):
        lineno = next(parser.stream).lineno  # skip endblock in {% sqlvm %}
        body = parser.parse_statements(end_tokens=["name:endsqlvm"], drop_needle=True)
        return nodes.CallBlock(self.call_method("thunk_interpret", []), [], [], body)

    def thunk_interpret(self, caller):
        """Interprets the enclosing block twice."""
        output = caller()
        parse = self.environment.parse(output)
        template = self.environment.from_string(parse)
        return template.render()

    @staticmethod
    def _template_call(stream, function_name):
        lineno = stream.current.lineno
        yield from (
            Token(lineno, "variable_begin", "{{"),
            Token(lineno, "name", function_name),
            Token(lineno, "lparen", "("),
            Token(lineno, "rparen", ")"),
            Token(lineno, "variable_end", "}}"),
        )

    @staticmethod
    def _visit_data(stream, state):
        if not state["processing"]:
            yield from SqlvmExtension._pass_along_visitor(stream, state)
            return

        lines = stream.current.value.split("\n")
        for line in lines[:-1]:
            if line and not line.isspace():
                yield Token(stream.current.lineno, "data", line)
                state["statement_started"] = True

            if state["statement_started"]:
                yield from SqlvmExtension._template_call(stream, "statement")
                state["statement_started"] = False

        yield Token(stream.current.lineno, "data", lines[-1])
        next(stream)

    @staticmethod
    def _visit_variable_begin(stream, state):
        if state["processing"]:
            # These could theoretically be empty, but we have no choice
            # but to assume that they'll return something.
            state["statement_started"] = True

        yield from SqlvmExtension._pass_along_visitor(stream, state)

    @staticmethod
    def _visit_block_begin(stream, state):
        if stream.look().test("name:sqlvm"):
            if state["processing"]:
                fail_template(stream, "Unexpected nested sqlvm block.")
            state["processing"] = True

            # We want our prologue to start after the block, so that it is
            # included in parsing.
            for expected_token in "block_begin", "name:sqlvm", "block_end":
                if not stream.current.test(expected_token):
                    fail_template(
                        stream,
                        "Unexpected token in sqlvm block (wanted {} but got {}).".format(
                            expected_token, stream.current.type
                        ),
                    )
                yield from SqlvmExtension._pass_along_visitor(stream, state)

            yield from SqlvmExtension._template_call(stream, "prologue")
        elif stream.look().test("name:endsqlvm"):
            if not state["processing"]:
                fail_template(stream, "Unexpected endsqlvm block.")

            state["processing"] = False

            # Yield before we yield the current token, so that the epilogue is
            # included in the parsing above.
            yield from SqlvmExtension._template_call(stream, "epilogue")
            yield from SqlvmExtension._pass_along_visitor(stream, state)
        else:
            yield from SqlvmExtension._pass_along_visitor(stream, state)

    @staticmethod
    def _pass_along_visitor(stream, state):
        yield stream.current
        next(stream)

    def filter_stream(self, stream):
        state = {
            # Whether we are currently in a sqlvm block.
            "processing": False,
            # Keeps track of whether it seems we have a non-trivial (i.e., not all
            # whitespace) statement.
            "statement_started": True,
        }

        visitors = {
            "data": SqlvmExtension._visit_data,
            "variable_begin": SqlvmExtension._visit_variable_begin,
            "block_begin": SqlvmExtension._visit_block_begin,
        }

        # We exit the loop when next(stream) throws StopIteration.
        while True:
            visitor = visitors.get(
                stream.current.type, SqlvmExtension._pass_along_visitor
            )
            yield from visitor(stream, state)
