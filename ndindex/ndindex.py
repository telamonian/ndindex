import ast
import inspect
import numbers

from numpy import ndarray, bool_, newaxis

def ndindex(obj):
    """
    Convert an object into an ndindex type

    Invalid indices will raise `IndexError`.

    >>> from ndindex import ndindex
    >>> ndindex(1)
    Integer(1)
    >>> ndindex(slice(0, 10))
    Slice(0, 10, None)

    """
    from . import Integer, Slice, Tuple, ellipsis, Newaxis, IntegerArray, BooleanArray

    if isinstance(obj, NDIndex):
        return obj

    if isinstance(obj, (list, ndarray, bool, bool_)):
        try:
            return IntegerArray(obj)
        except TypeError:
            pass
        try:
            return BooleanArray(obj)
        except TypeError:
            pass

        # Match the NumPy exceptions
        if isinstance(obj, ndarray):
            raise IndexError("arrays used as indices must be of integer (or boolean) type")
        else:
            raise IndexError("only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices")

    try:
        # If operator.index() works, use that
        return Integer(obj)
    except TypeError:
        pass

    if isinstance(obj, slice):
        return Slice(obj)

    if isinstance(obj, tuple):
        return Tuple(*obj)

    if obj == ellipsis:
        raise IndexError("Got ellipsis class. Did you mean to use the instance, ellipsis()?")
    if obj is Ellipsis:
        return ellipsis()

    if obj == newaxis:
        return Newaxis()

    raise IndexError("only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices")

class classproperty(object):
    def __init__(self, f):
        self.f = f
    def __get__(self, obj, owner):
        return self.f(owner)

class _Guard:
    def __init__(self):
        self.val = False

    def __call__(self):
        if self.val:
            return True
        else:
            self.val = True
            return False

def parse_index(node_or_string):
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
    def _raise_nested_tuple_node(node):
        raise ValueError(f'tuples inside of tuple indices are not supported: {node!r}')

    # from cpy37, should work until they remove ast.Num (not until cpy310)
    def _convert_num(node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, complex)):
                return node.value
        elif isinstance(node, ast.Num):
            # ast.Num was removed from ast grammar in cpy38
            return node.n
        _raise_malformed_node(node)
    def _convert_signed_num(node):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = _convert_num(node.operand)
            if isinstance(node.op, ast.UAdd):
                return + operand
            else:
                return - operand
        return _convert_num(node)

    _nested_tuple_guard = _Guard()
    def _convert(node):
        if isinstance(node, ast.Tuple):
            if _nested_tuple_guard():
                _raise_nested_tuple_node(node)

            return tuple(map(_convert, node.elts))
        elif isinstance(node, ast.List):
            return list(map(_convert, node.elts))
        elif isinstance(node, ast.Slice):
            return slice(
                _convert(node.lower) if node.lower is not None else None,
                _convert(node.upper) if node.upper is not None else None,
                _convert(node.step) if node.step is not None else None,
            )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'slice' and node.keywords == []:
            # support for parsing slices written out as 'slice(...)' objects
            return slice(*map(_convert, node.args))
        elif isinstance(node, ast.NameConstant) and node.value is None:
            # support for literal None in slices, eg 'slice(None, ...)'
            return None
        elif isinstance(node, ast.Ellipsis):
            # support for three dot '...' ellipsis syntax
            return ...
        elif isinstance(node, ast.Name) and node.id == 'Ellipsis':
            # support for 'Ellipsis' ellipsis syntax
            return ...
        elif isinstance(node, ast.Index):
            # ast.Index was removed from ast grammar in cpy39
            return _convert(node.value)
        elif isinstance(node, ast.ExtSlice):
            # ast.ExtSlice was removed from ast grammar in cpy39
            _nested_tuple_guard()
            return tuple(map(_convert, node.dims))

        return _convert_signed_num(node)
    return ndindex(_convert(node_or_string))


class NDIndex:
    """
    Represents an index into an nd-array (i.e., a numpy array).

    This is a base class for all ndindex types. All types that subclass this
    class should redefine the following methods

    - `_typecheck(self, *args)` should do type checking and basic type
      canonicalization, and either return a tuple of the new arguments for the
      class or raise an exception. Type checking means it should raise
      exceptions for input types that are never semantically meaningful for
      numpy arrays, for example, floating point indices, using the same
      exceptions as numpy where possible. Basic type canonicalization means,
      for instance, converting integers into `int` using `operator.index()`.
      All other canonicalization should be done in the `reduce()` method. The
      `NDIndex` base constructor will automatically set `.args` to the
      arguments returned by this method. Classes should always be able to
      recreate themselves with `.args`, i.e., `type(idx)(*idx.args) == idx`
      should always hold.

    - `raw` (a **@property** method) should return the raw index that can be
      passed as an index to a numpy array.

    In addition other methods should be defined as necessary.

    - `__len__` should return the largest possible shape of an axis sliced by
      the index (for single-axis indices), or raise ValueError if no such
      maximum exists.

    - `reduce(shape=None)` should reduce an index to an equivalent form for
      arrays of shape `shape`, or raise an `IndexError`. The error messages
      should match numpy as much as possible. The class of the equivalent
      index may be different. If `shape` is `None`, it should return a
      canonical form that is equivalent for all array shapes (assuming no
      IndexErrors).

    The methods `__init__`, `__eq__`, and `__hash__` should *not* be
    overridden. Equality (and hashability) on `NDIndex` subclasses is
    determined by equality of types and `.args`. Equivalent indices should not
    attempt to redefine equality. Rather they should define canonicalization
    via `reduce()`.

    """
    def __init__(self, *args, **kwargs):
        """
        This method should be called by subclasses (via super()) after type-checking
        """
        args = self._typecheck(*args, **kwargs)
        self.args = args
        """
        `idx.args` contains the arguments needed to create `idx`.

        For an ndindex object `idx`, `idx.args` is always a tuple such that

        .. code:: python

           type(idx)(*idx.args) == idx

        For :any:`Tuple` indices, the elements
        of `.args` are themselves ndindex types. For other types, `.args`
        contains raw Python types. Note that `.args` contains NumPy arrays for
        :any:`IntegerArray` and :any:`BooleanArray` types, so one should
        always do equality testing or hashing on the ndindex type itself, not
        its `.args`.

        For an object that represents an indexable version of `idx`, use
        :any:`.raw <raw>`.

        See Also
        ========

        raw
        """
    @classproperty
    def __signature__(self):
        """
        Allow Python 3's inspect.signature to give a useful signature for
        NDIndex subclasses.
        """
        sig = inspect.signature(self._typecheck)
        d = dict(sig.parameters)
        d.pop('self')
        return inspect.Signature(d.values())

    def __repr__(self):
        return f"{self.__class__.__name__}({', '.join(map(repr, self.args))})"

    def __str__(self):
        return f"{self.__class__.__name__}({', '.join(map(str, self.args))})"

    def __eq__(self, other):
        if not isinstance(other, NDIndex):
            try:
                other = ndindex(other)
            except IndexError:
                return False

        def test_equal(a, b):
            """
            Check if a == b, allowing for numpy arrays
            """
            if not (isinstance(a, b.__class__)
                    or isinstance(b, a.__class__)):
                return False
            if isinstance(a, ndarray):
                return a.shape == b.shape and (a == b).all()
            if isinstance(a, tuple):
                return len(a) == len(b) and all(test_equal(i, j) for i, j in
                                                zip(a, b))
            if isinstance(a, NDIndex):
                return test_equal(a.args, b.args)

            return a == b

        return test_equal(self, other)

    def __hash__(self):
        return hash(self.args)

    # TODO: Make NDIndex an abstract base class
    @property
    def raw(self):
        """
        Return the equivalent of `self` that can be used as an index

        NumPy does not allow custom objects to be used as indices, with the
        exception of integer indices, so to use an ndindex object as an
        index, it is necessary to use `raw`.

        >>> from ndindex import Slice
        >>> import numpy as np
        >>> a = np.arange(5)
        >>> s = Slice(2, 4)
        >>> a[s]
        Traceback (most recent call last):
        ...
        IndexError: only integers, slices (`:`), ellipsis (`...`), numpy.newaxis (`None`) and integer or boolean arrays are valid indices
        >>> a[s.raw]
        array([2, 3])

        """
        raise NotImplementedError

    def reduce(self, shape=None):
        """
        Simplify an index given that it will be applied to an array of a given shape.

        If `shape` is None (the default), the index will be canonicalized as
        much as possible while still staying equivalent for all array shapes
        that it does not raise IndexError for.

        Either returns a new index type, which is equivalent on arrays of
        shape `shape`, or raises IndexError if the index would give an index
        error (for instance, out of bounds integer index or too many indices
        for array).

        >>> from ndindex import Slice, Integer
        >>> Slice(0, 10).reduce((5,))
        Slice(0, 5, 1)
        >>> Integer(10).reduce((5,))
        Traceback (most recent call last):
        ...
        IndexError: index 10 is out of bounds for axis 0 with size 5

        For single axis indices such as Slice and Tuple, `reduce` takes an
        optional `axis` argument to specify the axis, defaulting to 0.

        See Also
        ========

        .Integer.reduce
        .Tuple.reduce
        .Slice.reduce
        .ellipsis.reduce
        .Newaxis.reduce
        .IntegerArray.reduce
        .BooleanArray.reduce

        """
        # XXX: Should the default be raise NotImplementedError or return self?
        raise NotImplementedError

    def expand(self, shape):
        r"""
        Expand a Tuple index on an array of shape `shape`

        An expanded index is as explicit as possible. Unlike :any:`reduce
        <NDIndex.reduce>`, which tries to simplify an index and remove
        redundancies, `expand()` typically makes an index larger.

        If `self` is invalid for the given shape, an `IndexError` is raised.
        Otherwise, the returned index satisfies the following:

        - It is always a :any:`Tuple`.

        - All the elements of the :any:`Tuple` are recursively :any:`reduced
          <NDIndex.reduce>`.

        - The length of the `.args` is equal to the length of the shape plus
          the number of :any:`Newaxis` indices in `self` plus 1 if there is a
          scalar :any:`BooleanArray` (`True` or `False`).

        - The resulting :any:`Tuple` has no :any:`ellipses <ellipsis>`. If
          there are axes that would be matched by an ellipsis or an implicit
          ellipsis at the end of the tuple, `Slice(0, n, 1)` indices are
          inserted, where `n` is the corresponding axis of the `shape`.

        - Any array indices in `self` are broadcast together. If `self`
          contains array indices (:any:`IntegerArray` or :any:`BooleanArray`),
          then any :any:`Integer` indices are converted into
          :any:`IntegerArray` indices of shape `()` and broadcast. Note that
          broadcasting is done in a memory efficient way so that even if the
          broadcasted shape is large it will not take up more memory than the
          original.

        - Scalar :any:`BooleanArray` arguments (`True` or `False`) are
          combined into a single term (the same as with :any:`Tuple.reduce`).

        - Non-scalar :any:`BooleanArray`\ s are all converted into equivalent
          :any:`IntegerArray`\ s via `nonzero()` and broadcast.

        >>> from ndindex import Tuple, Slice
        >>> Slice(None).expand((2, 3))
        Tuple(slice(0, 2, 1), slice(0, 3, 1))

        >>> idx = Tuple(slice(0, 10), ..., None, -3)
        >>> idx.expand((5, 3))
        Tuple(slice(0, 5, 1), None, 0)
        >>> idx.expand((1, 2, 3))
        Tuple(slice(0, 1, 1), slice(0, 2, 1), None, 0)
        >>> idx.expand((5,))
        Traceback (most recent call last):
        ...
        IndexError: too many indices for array: array is 1-dimensional, but 2 were indexed
        >>> idx.expand((5, 2))
        Traceback (most recent call last):
        ...
        IndexError: index -3 is out of bounds for axis 1 with size 2

        >>> idx = Tuple(..., [0, 1], -1)
        >>> idx.expand((1, 2, 3))
        Tuple(slice(0, 1, 1), [0, 1], [2, 2])

        See Also
        ========

        .Tuple.reduce
        broadcast_arrays

        """
        from .tuple import Tuple

        return Tuple(self).expand(shape)

    def newshape(self, shape):
        """
        Returns the shape of `a[idx.raw]`, assuming `a` has shape `shape`.

        `shape` should be a tuple of ints, or an int, which is equivalent to a
        1-D shape.

        Raises `IndexError` if `self` would be out of shape for an array of
        shape `shape`.

        >>> from ndindex import Slice, Integer, Tuple
        >>> shape = (6, 7, 8)
        >>> Integer(1).newshape(shape)
        (7, 8)
        >>> Integer(10).newshape(shape)
        Traceback (most recent call last):
        ...
        IndexError: index 10 is out of bounds for axis 0 with size 6
        >>> Slice(2, 5).newshape(shape)
        (3, 7, 8)
        >>> Tuple(0, ..., Slice(1, 3)).newshape(shape)
        (7, 2)

        """
        raise NotImplementedError

    def as_subindex(self, index):
        """
        `i.as_subindex(j)` produces an index `k` such that `a[j][k]` gives all of
        the elements of `a[j]` that are also in `a[i]`.

        If `a[j]` is a subset of `a[i]`, then `a[j][k] == a[i]`. Otherwise,
        `a[j][k] == a[i & j]`, where `i & j` is the intersection of `i` and
        `j`, that is, the elements of `a` that are indexed by both `i` and
        `j`.

        For example, in the below diagram, `i` and `j` index a subset of the
        array `a`. `k = i.as_subindex(j)` is an index on `a[j]` that gives the
        subset of `a[j]` also included in `a[i]`::

             +------------ self ------------+
             |                              |
         ------------------- a -----------------------
                |                                 |
                +------------- index -------------+
                |                           |
                +- self.as_subindex(index) -+

        `i.as_subindex(j)` is currently only implemented when `j` is a slices
        with positive steps and nonnegative start and stop, or a Tuple of the
        same. To use it with slices with negative start or stop, call
        :meth:`reduce` with a shape first.

        `as_subindex` can be seen as the left-inverse of composition, that is,
        if `a[i] = a[j][k]`, then `k = i.as_subindex(j)`, so that `k "="
        (j^-1)[i]` (this only works as a true inverse if `j` is a subset of
        `i`).

        Note that due to symmetry, `a[j][i.as_subindex(j)]` and
        `a[i][j.as_subindex(i)]` will give the same subarrays of `a`, which
        will be the array that includes the elements indexed by both `a[i]`
        and `a[j]`.

        `i.as_subindex(j)` may raise `ValueError` in the case that the indices
        `i` and `j` do not intersect at all.

        Examples
        ========

        An example usage of `as_subindex` is to split an index up into
        subindices of chunks of an array. For example, say a 1-D array `a` is
        chunked up into chunks of size `N`, so that `a[0:N]`, `a[N:2*N]`,
        `[2*N:3*N]`, etc. are stored separately. Then an index `a[i]` can be
        reindexed onto the chunks via `i.as_subindex(Slice(0, N))`,
        `i.as_subindex(Slice(N, 2*N))`, etc.

        >>> from ndindex import Slice
        >>> i = Slice(5, 15)
        >>> j1 = Slice(0, 10)
        >>> j2 = Slice(10, 20)
        >>> a = list(range(20))
        >>> a[i.raw]
        [5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        >>> a[j1.raw]
        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        >>> a[j2.raw]
        [10, 11, 12, 13, 14, 15, 16, 17, 18, 19]

        >>> k1 = i.as_subindex(j1)
        >>> k1
        Slice(5, 10, 1)
        >>> k2 = i.as_subindex(j2)
        >>> k2
        Slice(0, 5, 1)
        >>> a[j1.raw][k1.raw]
        [5, 6, 7, 8, 9]
        >>> a[j2.raw][k2.raw]
        [10, 11, 12, 13, 14]

        """
        index = ndindex(index) # pragma: no cover
        raise NotImplementedError(f"{type(self).__name__}.as_subindex({type(index).__name__}) isn't implemented yet")

    def isempty(self, shape=None):
        """
        Returns whether self always indexes an empty array

        An empty array is an array whose shape contains at least one 0. Note
        that scalars (arrays with shape `()`) are not considered empty.

        `shape` can be `None` (the default), or an array shape. If it is
        `None`, isempty() will return `True` when `self` is always empty for
        any array shape. However, if it gives `False`, it could still give an
        empty array for some array shapes, but not all. If you know the shape
        of the array that will be indexed, you can call `idx.isempty(shape)`
        first and the result will be correct for arrays of shape `shape`. If
        `shape` is given and `self` would raise an `IndexError` on an array of
        shape `shape`, `isempty()` also raises `IndexError`.

        >>> from ndindex import Tuple, Slice
        >>> Tuple(0, slice(0, 1)).isempty()
        False
        >>> Tuple(0, slice(0, 0)).isempty()
        True
        >>> Slice(5, 10).isempty()
        False
        >>> Slice(5, 10).isempty(4)
        True

        See Also
        ========
        ndindex.Slice.__len__

        """
        raise NotImplementedError

    def broadcast_arrays(self):
        """
        Broadcast all the array indices in self to a common shape.

        The resulting index is equivalent in all contexts where the original
        index is allowed. However, it is possible for the original index to
        give an IndexError but for the new index to not, since integer array
        indices have less stringent shape requirements than boolean array
        indices. There are also some instances for empty indices
        (:any:`isempty` is True) where bounds would be checked before
        broadcasting but not after.

        Any :any:`BooleanArray` indices are converted to :any:`IntegerArray`
        indices. Furthermore, if there are :any:`BooleanArray` or
        :any:`IntegerArray` indices, then any :any:`Integer` indices are also
        converted into scalar :any:`IntegerArray` indices and broadcast.
        Furthermore, if there are multiple boolean scalar indices (`True` or
        `False`), they are combined into a single one.

        Note that array broadcastability is checked in the :any:`Tuple`
        constructor, so this method will not raise any exceptions.

        This is part of what is performed by :any:`expand`, but unlike
        :any:`expand`, this method does not do any other manipulations, and it
        does not require a shape.

        >>> from ndindex import Tuple
        >>> idx = Tuple([[False], [True], [True]], [[4], [5], [5]], -1)
        >>> print(idx.broadcast_arrays())
        Tuple(IntegerArray([[1 2] [1 2] [1 2]]),
              IntegerArray([[0 0] [0 0] [0 0]]),
              IntegerArray([[4 4] [5 5] [5 5]]),
              IntegerArray([[-1 -1] [-1 -1] [-1 -1]]))

        See Also
        ========

        expand

        """
        return self

def asshape(shape, axis=None):
    """
    Cast `shape` as a valid NumPy shape.

    The input can be an integer `n`, which is equivalent to `(n,)`, or a tuple
    of integers.

    If the `axis` argument is provided, an `IndexError` is raised if it is out
    of bounds for the shape.

    The resulting shape is always a tuple of nonnegative integers.

    All ndindex functions that take a shape input should use::

        shape = asshape(shape)

    or::

        shape = asshape(shape, axis=axis)

    """
    from .integer import Integer
    from .tuple import Tuple
    if isinstance(shape, (Tuple, Integer)):
        raise TypeError("ndindex types are not meant to be used as a shape - "
                        "did you mean to use the built-in tuple type?")

    if isinstance(shape, numbers.Number):
        shape = (operator_index(shape),)

    try:
        l = len(shape)
    except TypeError:
        raise TypeError("expected sequence object with len >= 0 or a single integer")

    newshape = []
    # numpy uses __getitem__ rather than __iter__ to index into shape, so we
    # match that
    for i in range(l):
        # Raise TypeError if invalid
        newshape.append(operator_index(shape[i]))

        if shape[i] < 0:
            raise ValueError("unknown (negative) dimensions are not supported")

    if axis is not None:
        if len(newshape) <= axis:
            raise IndexError(f"too many indices for array: array is {len(shape)}-dimensional, but {axis + 1} were indexed")

    return tuple(newshape)


def operator_index(idx):
    """
    Convert `idx` into an integer index using `__index__()` or raise
    `TypeError`.

    This is the same as `operator.index()` except it disallows boolean types.

    This is a slight break in NumPy compatibility, as NumPy allows bools in
    some contexts where `__index__()` is used, for instance, in slices. It
    does disallow it in others, such as in shapes. The main motivation for
    disallowing bools entirely is 1) `numpy.bool_.__index__()` is deprecated
    (currently it matches the built-in `bool.__index__()` and returns the
    object unchanged, but prints a deprecation warning), and 2) for raw
    indices, booleans and `0`/`1` are completely different, i.e., `a[True]` is
    *not* the same as `a[1]`.

    >>> from ndindex.ndindex import operator_index
    >>> operator_index(1)
    1
    >>> operator_index(1.0)
    Traceback (most recent call last):
    ...
    TypeError: 'float' object cannot be interpreted as an integer
    >>> operator_index(True)
    Traceback (most recent call last):
    ...
    TypeError: 'bool' object cannot be interpreted as an integer

    """
    import operator

    if isinstance(idx, bool):
        raise TypeError("'bool' object cannot be interpreted as an integer")
    if isinstance(idx, bool_):
        raise TypeError("'np.bool_' object cannot be interpreted as an integer")
    return operator.index(idx)
