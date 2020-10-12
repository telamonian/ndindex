import ast
import sys

def literal_eval_slice(node_or_string):
    """
    "Safely" (needs validation) evaluate an expression node or a string containing
    a (limited subset) of valid numpy index or slice expressions.
    """
    if isinstance(node_or_string, str):
        node_or_string = ast.parse('dummy[{}]'.format(node_or_string.lstrip(" \t")) , mode='eval')
    if isinstance(node_or_string, ast.Expression):
        node_or_string = node_or_string.body
    if isinstance(node_or_string, ast.Subscript):
        node_or_string = node_or_string.slice

    def _raise_malformed_node(node):
        raise ValueError(f'malformed node or string: {node!r}')

    # from cpy37, should work until they remove ast.Num (not until cpy310)
    def _convert_num(node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, complex)):
                return node.value
        elif isinstance(node, ast.Num):
            return node.n
        raise ValueError('malformed node or string: ' + repr(node))
    def _convert_signed_num(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = _convert_num(node.operand)
            if isinstance(node.op, ast.UAdd):
                return + operand
            else:
                return - operand
        return _convert_num(node)

    def _convert(node):
        if isinstance(node, ast.Constant):
            return node.value
        elif isinstance(node, ast.Tuple):
            return tuple(map(_convert, node.elts))
        elif isinstance(node, ast.List):
            return list(map(_convert, node.elts))
        elif isinstance(node, ast.Slice):
            return slice(
                _convert(node.lower) if node.lower is not None else None,
                _convert(node.upper) if node.upper is not None else None,
                _convert(node.step) if node.step is not None else None,
            )

        if sys.version_info.major == 3 and sys.version_info.minor < 9:
            if sys.version_info.minor < 8:
                # ast.Num was removed (all uses replaced with ast.Constant) in cpy38
                if isinstance(node, ast.Num):
                    return node.n

            # ast.Index and ast.ExtSlice were removed in cpy39
            if isinstance(node, ast.Index):
                return _convert(node.value)
            elif isinstance(node, ast.ExtSlice):
                return tuple(map(_convert, node.dims))

        return _convert_signed_num(node)
    return _convert(node_or_string)
