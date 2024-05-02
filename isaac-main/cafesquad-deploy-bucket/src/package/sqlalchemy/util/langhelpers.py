# util/langhelpers.py
# Copyright (C) 2005-2022 the SQLAlchemy authors and contributors
# <see AUTHORS file>
#
# This module is part of SQLAlchemy and is released under
# the MIT License: https://www.opensource.org/licenses/mit-license.php

"""Routines to help with the creation, loading and introspection of
modules, classes, hierarchies, attributes, functions, and methods.

"""

import collections
from functools import update_wrapper
import hashlib
import inspect
import itertools
import operator
import re
import sys
import textwrap
import types
import warnings

from . import _collections
from . import compat
from .. import exc


def md5_hex(x):
    if compat.py3k:
        x = x.encode("utf-8")
    m = hashlib.md5()
    m.update(x)
    return m.hexdigest()


class safe_reraise(object):
    """Reraise an exception after invoking some
    handler code.

    Stores the existing exception info before
    invoking so that it is maintained across a potential
    coroutine context switch.

    e.g.::

        try:
            sess.commit()
        except:
            with safe_reraise():
                sess.rollback()

    """

    __slots__ = ("warn_only", "_exc_info")

    def __init__(self, warn_only=False):
        self.warn_only = warn_only

    def __enter__(self):
        self._exc_info = sys.exc_info()

    def __exit__(self, type_, value, traceback):
        # see #2703 for notes
        if type_ is None:
            exc_type, exc_value, exc_tb = self._exc_info
            self._exc_info = None  # remove potential circular references
            if not self.warn_only:
                compat.raise_(
                    exc_value,
                    with_traceback=exc_tb,
                )
        else:
            if not compat.py3k and self._exc_info and self._exc_info[1]:
                # emulate Py3K's behavior of telling us when an exception
                # occurs in an exception handler.
                warn(
                    "An exception has occurred during handling of a "
                    "previous exception.  The previous exception "
                    "is:\n %s %s\n" % (self._exc_info[0], self._exc_info[1])
                )
            self._exc_info = None  # remove potential circular references
            compat.raise_(value, with_traceback=traceback)


def walk_subclasses(cls):
    seen = set()

    stack = [cls]
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        else:
            seen.add(cls)
        stack.extend(cls.__subclasses__())
        yield cls


def string_or_unprintable(element):
    if isinstance(element, compat.string_types):
        return element
    else:
        try:
            return str(element)
        except Exception:
            return "unprintable element %r" % element


def clsname_as_plain_name(cls):
    return " ".join(
        n.lower() for n in re.findall(r"([A-Z][a-z]+)", cls.__name__)
    )


def method_is_overridden(instance_or_cls, against_method):
    """Return True if the two class methods don't match."""

    if not isinstance(instance_or_cls, type):
        current_cls = instance_or_cls.__class__
    else:
        current_cls = instance_or_cls

    method_name = against_method.__name__

    current_method = getattr(current_cls, method_name)

    return current_method != against_method


def decode_slice(slc):
    """decode a slice object as sent to __getitem__.

    takes into account the 2.5 __index__() method, basically.

    """
    ret = []
    for x in slc.start, slc.stop, slc.step:
        if hasattr(x, "__index__"):
            x = x.__index__()
        ret.append(x)
    return tuple(ret)


def _unique_symbols(used, *bases):
    used = set(used)
    for base in bases:
        pool = itertools.chain(
            (base,),
            compat.itertools_imap(lambda i: base + str(i), range(1000)),
        )
        for sym in pool:
            if sym not in used:
                used.add(sym)
                yield sym
                break
        else:
            raise NameError("exhausted namespace for symbol base %s" % base)


def map_bits(fn, n):
    """Call the given function given each nonzero bit from n."""

    while n:
        b = n & (~n + 1)
        yield fn(b)
        n ^= b


def decorator(target):
    """A signature-matching decorator factory."""

    def decorate(fn):
        if not inspect.isfunction(fn) and not inspect.ismethod(fn):
            raise Exception("not a decoratable function")

        spec = compat.inspect_getfullargspec(fn)
        env = {}

        spec = _update_argspec_defaults_into_env(spec, env)

        names = tuple(spec[0]) + spec[1:3] + (fn.__name__,)
        targ_name, fn_name = _unique_symbols(names, "target", "fn")

        metadata = dict(target=targ_name, fn=fn_name)
        metadata.update(format_argspec_plus(spec, grouped=False))
        metadata["name"] = fn.__name__
        code = (
            """\
def %(name)s(%(args)s):
    return %(target)s(%(fn)s, %(apply_kw)s)
"""
            % metadata
        )
        env.update({targ_name: target, fn_name: fn, "__name__": fn.__module__})

        decorated = _exec_code_in_env(code, env, fn.__name__)
        decorated.__defaults__ = getattr(fn, "__func__", fn).__defaults__
        decorated.__wrapped__ = fn
        return update_wrapper(decorated, fn)

    return update_wrapper(decorate, target)


def _update_argspec_defaults_into_env(spec, env):
    """given a FullArgSpec, convert defaults to be symbol names in an env."""

    if spec.defaults:
        new_defaults = []
        i = 0
        for arg in spec.defaults:
            if type(arg).__module__ not in ("builtins", "__builtin__"):
                name = "x%d" % i
                env[name] = arg
                new_defaults.append(name)
                i += 1
            else:
                new_defaults.append(arg)
        elem = list(spec)
        elem[3] = tuple(new_defaults)
        return compat.FullArgSpec(*elem)
    else:
        return spec


def _exec_code_in_env(code, env, fn_name):
    exec(code, env)
    return env[fn_name]


def public_factory(target, location, class_location=None):
    """Produce a wrapping function for the given cls or classmethod.

    Rationale here is so that the __init__ method of the
    class can serve as documentation for the function.

    """

    if isinstance(target, type):
        fn = target.__init__
        callable_ = target
        doc = (
            "Construct a new :class:`%s` object. \n\n"
            "This constructor is mirrored as a public API function; "
            "see :func:`sqlalchemy%s` "
            "for a full usage and argument description."
            % (
                class_location if class_location else ".%s" % target.__name__,
                location,
            )
        )
    else:
        fn = callable_ = target
        doc = (
            "This function is mirrored; see :func:`sqlalchemy%s` "
            "for a description of arguments." % location
        )

    location_name = location.split(".")[-1]
    spec = compat.inspect_getfullargspec(fn)
    del spec[0][0]
    metadata = format_argspec_plus(spec, grouped=False)
    metadata["name"] = location_name
    code = (
        """\
def %(name)s(%(args)s):
    return cls(%(apply_kw)s)
"""
        % metadata
    )
    env = {
        "cls": callable_,
        "symbol": symbol,
        "__name__": callable_.__module__,
    }
    exec(code, env)
    decorated = env[location_name]

    if hasattr(fn, "_linked_to"):
        linked_to, linked_to_location = fn._linked_to
        linked_to_doc = linked_to.__doc__
        if class_location is None:
            class_location = "%s.%s" % (target.__module__, target.__name__)

        linked_to_doc = inject_docstring_text(
            linked_to_doc,
            ".. container:: inherited_member\n\n    "
            "This documentation is inherited from :func:`sqlalchemy%s`; "
            "this constructor, :func:`sqlalchemy%s`,   "
            "creates a :class:`sqlalchemy%s` object.  See that class for "
            "additional details describing this subclass."
            % (linked_to_location, location, class_location),
            1,
        )
        decorated.__doc__ = linked_to_doc
    else:
        decorated.__doc__ = fn.__doc__

    decorated.__module__ = "sqlalchemy" + location.rsplit(".", 1)[0]
    if decorated.__module__ not in sys.modules:
        raise ImportError(
            "public_factory location %s is not in sys.modules"
            % (decorated.__module__,)
        )

    if compat.py2k or hasattr(fn, "__func__"):
        fn.__func__.__doc__ = doc
        if not hasattr(fn.__func__, "_linked_to"):
            fn.__func__._linked_to = (decorated, location)
    else:
        fn.__doc__ = doc
        if not hasattr(fn, "_linked_to"):
            fn._linked_to = (decorated, location)

    return decorated


class PluginLoader(object):
    def __init__(self, group, auto_fn=None):
        self.group = group
        self.impls = {}
        self.auto_fn = auto_fn

    def clear(self):
        self.impls.clear()

    def load(self, name):
        if name in self.impls:
            return self.impls[name]()

        if self.auto_fn:
            loader = self.auto_fn(name)
            if loader:
                self.impls[name] = loader
                return loader()

        for impl in compat.importlib_metadata_get(self.group):
            if impl.name == name:
                self.impls[name] = impl.load
                return impl.load()

        raise exc.NoSuchModuleError(
            "Can't load plugin: %s:%s" % (self.group, name)
        )

    def register(self, name, modulepath, objname):
        def load():
            mod = compat.import_(modulepath)
            for token in modulepath.split(".")[1:]:
                mod = getattr(mod, token)
            return getattr(mod, objname)

        self.impls[name] = load


def _inspect_func_args(fn):
    try:
        co_varkeywords = inspect.CO_VARKEYWORDS
    except AttributeError:
        # https://docs.python.org/3/library/inspect.html
        # The flags are specific to CPython, and may not be defined in other
        # Python implementations. Furthermore, the flags are an implementation
        # detail, and can be removed or deprecated in future Python releases.
        spec = compat.inspect_getfullargspec(fn)
        return spec[0], bool(spec[2])
    else:
        # use fn.__code__ plus flags to reduce method call overhead
        co = fn.__code__
        nargs = co.co_argcount
        return (
            list(co.co_varnames[:nargs]),
            bool(co.co_flags & co_varkeywords),
        )


def get_cls_kwargs(cls, _set=None):
    r"""Return the full set of inherited kwargs for the given `cls`.

    Probes a class's __init__ method, collecting all named arguments.  If the
    __init__ defines a \**kwargs catch-all, then the constructor is presumed
    to pass along unrecognized keywords to its base classes, and the
    collection process is repeated recursively on each of the bases.

    Uses a subset of inspect.getfullargspec() to cut down on method overhead,
    as this is used within the Core typing system to create copies of type
    objects which is a performance-sensitive operation.

    No anonymous tuple arguments please !

    """
    toplevel = _set is None
    if toplevel:
        _set = set()

    ctr = cls.__dict__.get("__init__", False)

    has_init = (
        ctr
        and isinstance(ctr, types.FunctionType)
        and isinstance(ctr.__code__, types.CodeType)
    )

    if has_init:
        names, has_kw = _inspect_func_args(ctr)
        _set.update(names)

        if not has_kw and not toplevel:
            return None

    if not has_init or has_kw:
        for c in cls.__bases__:
            if get_cls_kwargs(c, _set) is None:
                break

    _set.discard("self")
    return _set


def get_func_kwargs(func):
    """Return the set of legal kwargs for the given `func`.

    Uses getargspec so is safe to call for methods, functions,
    etc.

    """

    return compat.inspect_getfullargspec(func)[0]


def get_callable_argspec(fn, no_self=False, _is_init=False):
    """Return the argument signature for any callable.

    All pure-Python callables are accepted, including
    functions, methods, classes, objects with __call__;
    builtins and other edge cases like functools.partial() objects
    raise a TypeError.

    """
    if inspect.isbuiltin(fn):
        raise TypeError("Can't inspect builtin: %s" % fn)
    elif inspect.isfunction(fn):
        if _is_init and no_self:
            spec = compat.inspect_getfullargspec(fn)
            return compat.FullArgSpec(
                spec.args[1:],
                spec.varargs,
                spec.varkw,
                spec.defaults,
                spec.kwonlyargs,
                spec.kwonlydefaults,
                spec.annotations,
            )
        else:
            return compat.inspect_getfullargspec(fn)
    elif inspect.ismethod(fn):
        if no_self and (_is_init or fn.__self__):
            spec = compat.inspect_getfullargspec(fn.__func__)
            return compat.FullArgSpec(
                spec.args[1:],
                spec.varargs,
                spec.varkw,
                spec.defaults,
                spec.kwonlyargs,
                spec.kwonlydefaults,
                spec.annotations,
            )
        else:
            return compat.inspect_getfullargspec(fn.__func__)
    elif inspect.isclass(fn):
        return get_callable_argspec(
            fn.__init__, no_self=no_self, _is_init=True
        )
    elif hasattr(fn, "__func__"):
        return compat.inspect_getfullargspec(fn.__func__)
    elif hasattr(fn, "__call__"):
        if inspect.ismethod(fn.__call__):
            return get_callable_argspec(fn.__call__, no_self=no_self)
        else:
            raise TypeError("Can't inspect callable: %s" % fn)
    else:
        raise TypeError("Can't inspect callable: %s" % fn)


def format_argspec_plus(fn, grouped=True):
    """Returns a dictionary of formatted, introspected function arguments.

    A enhanced variant of inspect.formatargspec to support code generation.

    fn
       An inspectable callable or tuple of inspect getargspec() results.
    grouped
      Defaults to True; include (parens, around, argument) lists

    Returns:

    args
      Full inspect.formatargspec for fn
    self_arg
      The name of the first positional argument, varargs[0], or None
      if the function defines no positional arguments.
    apply_pos
      args, re-written in calling rather than receiving syntax.  Arguments are
      passed positionally.
    apply_kw
      Like apply_pos, except keyword-ish args are passed as keywords.
    apply_pos_proxied
      Like apply_pos but omits the self/cls argument

    Example::

      >>> format_argspec_plus(lambda self, a, b, c=3, **d: 123)
      {'args': '(self, a, b, c=3, **d)',
       'self_arg': 'self',
       'apply_kw': '(self, a, b, c=c, **d)',
       'apply_pos': '(self, a, b, c, **d)'}

    """
    if compat.callable(fn):
        spec = compat.inspect_getfullargspec(fn)
    else:
        spec = fn

    args = compat.inspect_formatargspec(*spec)

    apply_pos = compat.inspect_formatargspec(
        spec[0], spec[1], spec[2], None, spec[4]
    )

    if spec[0]:
        self_arg = spec[0][0]

        apply_pos_proxied = compat.inspect_formatargspec(
            spec[0][1:], spec[1], spec[2], None, spec[4]
        )

    elif spec[1]:
        # I'm not sure what this is
        self_arg = "%s[0]" % spec[1]

        apply_pos_proxied = apply_pos
    else:
        self_arg = None
        apply_pos_proxied = apply_pos

    num_defaults = 0
    if spec[3]:
        num_defaults += len(spec[3])
    if spec[4]:
        num_defaults += len(spec[4])
    name_args = spec[0] + spec[4]

    if num_defaults:
        defaulted_vals = name_args[0 - num_defaults :]
    else:
        defaulted_vals = ()

    apply_kw = compat.inspect_formatargspec(
        name_args,
        spec[1],
        spec[2],
        defaulted_vals,
        formatvalue=lambda x: "=" + x,
    )

    if spec[0]:
        apply_kw_proxied = compat.inspect_formatargspec(
            name_args[1:],
            spec[1],
            spec[2],
            defaulted_vals,
            formatvalue=lambda x: "=" + x,
        )
    else:
        apply_kw_proxied = apply_kw

    if grouped:
        return dict(
            args=args,
            self_arg=self_arg,
            apply_pos=apply_pos,
            apply_kw=apply_kw,
            apply_pos_proxied=apply_pos_proxied,
            apply_kw_proxied=apply_kw_proxied,
        )
    else:
        return dict(
            args=args[1:-1],
            self_arg=self_arg,
            apply_pos=apply_pos[1:-1],
            apply_kw=apply_kw[1:-1],
            apply_pos_proxied=apply_pos_proxied[1:-1],
            apply_kw_proxied=apply_kw_proxied[1:-1],
        )


def format_argspec_init(method, grouped=True):
    """format_argspec_plus with considerations for typical __init__ methods

    Wraps format_argspec_plus with error handling strategies for typical
    __init__ cases::

      object.__init__ -> (self)
      other unreflectable (usually C) -> (self, *args, **kwargs)

    """
    if method is object.__init__:
        args = "(self)" if grouped else "self"
        proxied = "()" if grouped else ""
    else:
        try:
            return format_argspec_plus(method, grouped=grouped)
        except TypeError:
            args = (
                "(self, *args, **kwargs)"
                if grouped
                else "self, *args, **kwargs"
            )
            proxied = "(*args, **kwargs)" if grouped else "*args, **kwargs"
    return dict(
        self_arg="self",
        args=args,
        apply_pos=args,
        apply_kw=args,
        apply_pos_proxied=proxied,
        apply_kw_proxied=proxied,
    )


def create_proxy_methods(
    target_cls,
    target_cls_sphinx_name,
    proxy_cls_sphinx_name,
    classmethods=(),
    methods=(),
    attributes=(),
):
    """A class decorator that will copy attributes to a proxy class.

    The class to be instrumented must define a single accessor "_proxied".

    """

    def decorate(cls):
        def instrument(name, clslevel=False):
            fn = getattr(target_cls, name)
            spec = compat.inspect_getfullargspec(fn)
            env = {"__name__": fn.__module__}

            spec = _update_argspec_defaults_into_env(spec, env)
            caller_argspec = format_argspec_plus(spec, grouped=False)

            metadata = {
                "name": fn.__name__,
                "apply_pos_proxied": caller_argspec["apply_pos_proxied"],
                "apply_kw_proxied": caller_argspec["apply_kw_proxied"],
                "args": caller_argspec["args"],
                "self_arg": caller_argspec["self_arg"],
            }

            if clslevel:
                code = (
                    "def %(name)s(%(args)s):\n"
                    "    return target_cls.%(name)s(%(apply_kw_proxied)s)"
                    % metadata
                )
                env["target_cls"] = target_cls
            else:
                code = (
                    "def %(name)s(%(args)s):\n"
                    "    return %(self_arg)s._proxied.%(name)s(%(apply_kw_proxied)s)"  # noqa: E501
                    % metadata
                )

            proxy_fn = _exec_code_in_env(code, env, fn.__name__)
            proxy_fn.__defaults__ = getattr(fn, "__func__", fn).__defaults__
            proxy_fn.__doc__ = inject_docstring_text(
                fn.__doc__,
                ".. container:: class_bases\n\n    "
                "Proxied for the %s class on behalf of the %s class."
                % (target_cls_sphinx_name, proxy_cls_sphinx_name),
                1,
            )

            if clslevel:
                proxy_fn = classmethod(proxy_fn)

            return proxy_fn

        def makeprop(name):
            attr = target_cls.__dict__.get(name, None)

            if attr is not None:
                doc = inject_docstring_text(
                    attr.__doc__,
                    ".. container:: class_bases\n\n    "
                    "Proxied for the %s class on behalf of the %s class."
                    % (
                        target_cls_sphinx_name,
                        proxy_cls_sphinx_name,
                    ),
                    1,
                )
            else:
                doc = None

            code = (
                "def set_(self, attr):\n"
                "    self._proxied.%(name)s = attr\n"
                "def get(self):\n"
                "    return self._proxied.%(name)s\n"
                "get.__doc__ = doc\n"
                "getset = property(get, set_)"
            ) % {"name": name}

            getset = _exec_code_in_env(code, {"doc": doc}, "getset")

            return getset

        for meth in methods:
            if hasattr(cls, meth):
                raise TypeError(
                    "class %s already has a method %s" % (cls, meth)
                )
            setattr(cls, meth, instrument(meth))

        for prop in attributes:
            if hasattr(cls, prop):
                raise TypeError(
                    "class %s already has a method %s" % (cls, prop)
                )
            setattr(cls, prop, makeprop(prop))

        for prop in classmethods:
            if hasattr(cls, prop):
                raise TypeError(
                    "class %s already has a method %s" % (cls, prop)
                )
            setattr(cls, prop, instrument(prop, clslevel=True))

        return cls

    return decorate


def getargspec_init(method):
    """inspect.getargspec with considerations for typical __init__ methods

    Wraps inspect.getargspec with error handling for typical __init__ cases::

      object.__init__ -> (self)
      other unreflectable (usually C) -> (self, *args, **kwargs)

    """
    try:
        return compat.inspect_getfullargspec(method)
    except TypeError:
        if method is object.__init__:
            return (["self"], None, None, None)
        else:
            return (["self"], "args", "kwargs", None)


def unbound_method_to_callable(func_or_cls):
    """Adjust the incoming callable such that a 'self' argument is not
    required.

    """

    if isinstance(func_or_cls, types.MethodType) and not func_or_cls.__self__:
        return func_or_cls.__func__
    else:
        return func_or_cls


def generic_repr(obj, additional_kw=(), to_inspect=None, omit_kwarg=()):
    """Produce a __repr__() based on direct association of the __init__()
    specification vs. same-named attributes present.

    """
    if to_inspect is None:
        to_inspect = [obj]
    else:
        to_inspect = _collections.to_list(to_inspect)

    missing = object()

    pos_args = []
    kw_args = _collections.OrderedDict()
    vargs = None
    for i, insp in enumerate(to_inspect):
        try:
            spec = compat.inspect_getfullargspec(insp.__init__)
        except TypeError:
            continue
        else:
            default_len = spec.defaults and len(spec.defaults) or 0
            if i == 0:
                if spec.varargs:
                    vargs = spec.varargs
                if default_len:
                    pos_args.extend(spec.args[1:-default_len])
                else:
                    pos_args.extend(spec.args[1:])
            else:
                kw_args.update(
                    [(arg, missing) for arg in spec.args[1:-default_len]]
                )

            if default_len:
                kw_args.update(
                    [
                        (arg, default)
                        for arg, default in zip(
                            spec.args[-default_len:], spec.defaults
                        )
                    ]
                )
    output = []

    output.extend(repr(getattr(obj, arg, None)) for arg in pos_args)

    if vargs is not None and hasattr(obj, vargs):
        output.extend([repr(val) for val in getattr(obj, vargs)])

    for arg, defval in kw_args.items():
        if arg in omit_kwarg:
            continue
        try:
            val = getattr(obj, arg, missing)
            if val is not missing and val != defval:
                output.append("%s=%r" % (arg, val))
        except Exception:
            pass

    if additional_kw:
        for arg, defval in additional_kw:
            try:
                val = getattr(obj, arg, missing)
                if val is not missing and val != defval:
                    output.append("%s=%r" % (arg, val))
            except Exception:
                pass

    return "%s(%s)" % (obj.__class__.__name__, ", ".join(output))


class portable_instancemethod(object):
    """Turn an instancemethod into a (parent, name) pair
    to produce a serializable callable.

    """

    __slots__ = "target", "name", "kwargs", "__weakref__"

    def __getstate__(self):
        return {
            "target": self.target,
            "name": self.name,
            "kwargs": self.kwargs,
        }

    def __setstate__(self, state):
        self.target = state["target"]
        self.name = state["name"]
        self.kwargs = state.get("kwargs", ())

    def __init__(self, meth, kwargs=()):
        self.target = meth.__self__
        self.name = meth.__name__
        self.kwargs = kwargs

    def __call__(self, *arg, **kw):
        kw.update(self.kwargs)
        return getattr(self.target, self.name)(*arg, **kw)


def class_hierarchy(cls):
    """Return an unordered sequence of all classes related to cls.

    Traverses diamond hierarchies.

    Fibs slightly: subclasses of builtin types are not returned.  Thus
    class_hierarchy(class A(object)) returns (A, object), not A plus every
    class systemwide that derives from object.

    Old-style classes are discarded and hierarchies rooted on them
    will not be descended.

    """
    if compat.py2k:
        if isinstance(cls, types.ClassType):
            return list()

    hier = {cls}
    process = list(cls.__mro__)
    while process:
        c = process.pop()
        if compat.py2k:
            if isinstance(c, types.ClassType):
                continue
            bases = (
                _
                for _ in c.__bases__
                if _ not in hier and not isinstance(_, types.ClassType)
            )
        else:
            bases = (_ for _ in c.__bases__ if _ not in hier)

        for b in bases:
            process.append(b)
            hier.add(b)

        if compat.py3k:
            if c.__module__ == "builtins" or not hasattr(c, "__subclasses__"):
                continue
        else:
            if c.__module__ == "__builtin__" or not hasattr(
                c, "__subclasses__"
            ):
                continue

        for s in [_ for _ in c.__subclasses__() if _ not in hier]:
            process.append(s)
            hier.add(s)
    return list(hier)


def iterate_attributes(cls):
    """iterate all the keys and attributes associated
    with a class, without using getattr().

    Does not use getattr() so that class-sensitive
    descriptors (i.e. property.__get__()) are not called.

    """
    keys = dir(cls)
    for key in keys:
        for c in cls.__mro__:
            if key in c.__dict__:
                yield (key, c.__dict__[key])
                break


def monkeypatch_proxied_specials(
    into_cls,
    from_cls,
    skip=None,
    only=None,
    name="self.proxy",
    from_instance=None,
):
    """Automates delegation of __specials__ for a proxying type."""

    if only:
        dunders = only
    else:
        if skip is None:
            skip = (
                "__slots__",
                "__del__",
                "__getattribute__",
                "__metaclass__",
                "__getstate__",
                "__setstate__",
            )
        dunders = [
            m
            for m in dir(from_cls)
            if (
                m.startswith("__")
                and m.endswith("__")
                and not hasattr(into_cls, m)
                and m not in skip
            )
        ]

    for method in dunders:
        try:
            fn = getattr(from_cls, method)
            if not hasattr(fn, "__call__"):
                continue
            fn = getattr(fn, "__func__", fn)
        except AttributeError:
            continue
        try:
            spec = compat.inspect_getfullargspec(fn)
            fn_args = compat.inspect_formatargspec(spec[0])
            d_args = compat.inspect_formatargspec(spec[0][1:])
        except TypeError:
            fn_args = "(self, *args, **kw)"
            d_args = "(*args, **kw)"

        py = (
            "def %(method)s%(fn_args)s: "
            "return %(name)s.%(method)s%(d_args)s" % locals()
        )

        env = from_instance is not None and {name: from_instance} or {}
        compat.exec_(py, env)
        try:
            env[method].__defaults__ = fn.__defaults__
        except AttributeError:
            pass
        setattr(into_cls, method, env[method])


def methods_equivalent(meth1, meth2):
    """Return True if the two methods are the same implementation."""

    return getattr(meth1, "__func__", meth1) is getattr(
        meth2, "__func__", meth2
    )


def as_interface(obj, cls=None, methods=None, required=None):
    """Ensure basic interface compliance for an instance or dict of callables.

    Checks that ``obj`` implements public methods of ``cls`` or has members
    listed in ``methods``. If ``required`` is not supplied, implementing at
    least one interface method is sufficient. Methods present on ``obj`` that
    are not in the interface are ignored.

    If ``obj`` is a dict and ``dict`` does not meet the interface
    requirements, the keys of the dictionary are inspected. Keys present in
    ``obj`` that are not in the interface will raise TypeErrors.

    Raises TypeError if ``obj`` does not meet the interface criteria.

    In all passing cases, an object with callable members is returned.  In the
    simple case, ``obj`` is returned as-is; if dict processing kicks in then
    an anonymous class is returned.

    obj
      A type, instance, or dictionary of callables.
    cls
      Optional, a type.  All public methods of cls are considered the
      interface.  An ``obj`` instance of cls will always pass, ignoring
      ``required``..
    methods
      Optional, a sequence of method names to consider as the interface.
    required
      Optional, a sequence of mandatory implementations. If omitted, an
      ``obj`` that provides at least one interface method is considered
      sufficient.  As a convenience, required may be a type, in which case
      all public methods of the type are required.

    """
    if not cls and not methods:
        raise TypeError("a class or collection of method names are required")

    if isinstance(cls, type) and isinstance(obj, cls):
        return obj

    interface = set(methods or [m for m in dir(cls) if not m.startswith("_")])
    implemented = set(dir(obj))

    complies = operator.ge
    if isinstance(required, type):
        required = interface
    elif not required:
        required = set()
        complies = operator.gt
    else:
        required = set(required)

    if complies(implemented.intersection(interface), required):
        return obj

    # No dict duck typing here.
    if not isinstance(obj, dict):
        qualifier = complies is operator.gt and "any of" or "all of"
        raise TypeError(
            "%r does not implement %s: %s"
            % (obj, qualifier, ", ".join(interface))
        )

    class AnonymousInterface(object):
        """A callable-holding shell."""

    if cls:
        AnonymousInterface.__name__ = "Anonymous" + cls.__name__
    found = set()

    for method, impl in dictlike_iteritems(obj):
        if method not in interface:
            raise TypeError("%r: unknown in this interface" % method)
        if not compat.callable(impl):
            raise TypeError("%r=%r is not callable" % (method, impl))
        setattr(AnonymousInterface, method, staticmethod(impl))
        found.add(method)

    if complies(found, required):
        return AnonymousInterface

    raise TypeError(
        "dictionary does not contain required keys %s"
        % ", ".join(required - found)
    )


class memoized_property(object):
    """A read-only @property that is only evaluated once."""

    def __init__(self, fget, doc=None):
        self.fget = fget
        self.__doc__ = doc or fget.__doc__
        self.__name__ = fget.__name__

    def __get__(self, obj, cls):
        if obj is None:
            return self
        obj.__dict__[self.__name__] = result = self.fget(obj)
        return result

    def _reset(self, obj):
        memoized_property.reset(obj, self.__name__)

    @classmethod
    def reset(cls, obj, name):
        obj.__dict__.pop(name, None)


def memoized_instancemethod(fn):
    """Decorate a method memoize its return value.

    Best applied to no-arg methods: memoization is not sensitive to
    argument values, and will always return the same value even when
    called with different arguments.

    """

    def oneshot(self, *args, **kw):
        result = fn(self, *args, **kw)

        def memo(*a, **kw):
            return result

        memo.__name__ = fn.__name__
        memo.__doc__ = fn.__doc__
        self.__dict__[fn.__name__] = memo
        return result

    return update_wrapper(oneshot, fn)


class HasMemoized(object):
    """A class that maintains the names of memoized elements in a
    collection for easy cache clearing, generative, etc.

    """

    __slots__ = ()

    _memoized_keys = frozenset()

    def _reset_memoizations(self):
        for elem in self._memoized_keys:
            self.__dict__.pop(elem, None)

    def _assert_no_memoizations(self):
        for elem in self._memoized_keys:
            assert elem not in self.__dict__

    def _set_memoized_attribute(self, key, value):
        self.__dict__[key] = value
        self._memoized_keys |= {key}

    class memoized_attribute(object):
        """A read-only @property that is only evaluated once.

        :meta private:

        """

        def __init__(self, fget, doc=None):
            self.fget = fget
            self.__doc__ = doc or fget.__doc__
            self.__name__ = fget.__name__

        def __get__(self, obj, cls):
            if obj is None:
                return self
            obj.__dict__[self.__name__] = result = self.fget(obj)
            obj._memoized_keys |= {self.__name__}
            return result

    @classmethod
    def memoized_instancemethod(cls, fn):
        """Decorate a method memoize its return value."""

        def oneshot(self, *args, **kw):
            result = fn(self, *args, **kw)

            def memo(*a, **kw):
                return result

            memo.__name__ = fn.__name__
            memo.__doc__ = fn.__doc__
            self.__dict__[fn.__name__] = memo
            self._memoized_keys |= {fn.__name__}
            return result

        return update_wrapper(oneshot, fn)


class MemoizedSlots(object):
    """Apply memoized items to an object using a __getattr__ scheme.

    This allows the functionality of memoized_property and
    memoized_instancemethod to be available to a class using __slots__.

    """

    __slots__ = ()

    def _fallback_getattr(self, key):
        raise AttributeError(key)

    def __getattr__(self, key):
        if key.startswith("_memoized"):
            raise AttributeError(key)
        elif hasattr(self, "_memoized_attr_%s" % key):
            value = getattr(self, "_memoized_attr_%s" % key)()
            setattr(self, key, value)
            return value
        elif hasattr(self, "_memoized_method_%s" % key):
            fn = getattr(self, "_memoized_method_%s" % key)

            def oneshot(*args, **kw):
                result = fn(*args, **kw)

                def memo(*a, **kw):
                    return result

                memo.__name__ = fn.__name__
                memo.__doc__ = fn.__doc__
                setattr(self, key, memo)
                return result

            oneshot.__doc__ = fn.__doc__
            return oneshot
        else:
            return self._fallback_getattr(key)


# from paste.deploy.converters
def asbool(obj):
    if isinstance(obj, compat.string_types):
        obj = obj.strip().lower()
        if obj in ["true", "yes", "on", "y", "t", "1"]:
            return True
        elif obj in ["false", "no", "off", "n", "f", "0"]:
            return False
        else:
            raise ValueError("String is not true/false: %r" % obj)
    return bool(obj)


def bool_or_str(*text):
    """Return a callable that will evaluate a string as
    boolean, or one of a set of "alternate" string values.

    """

    def bool_or_value(obj):
        if obj in text:
            return obj
        else:
            return asbool(obj)

    return bool_or_value


def asint(value):
    """Coerce to integer."""

    if value is None:
        return value
    return int(value)


def coerce_kw_type(kw, key, type_, flexi_bool=True, dest=None):
    r"""If 'key' is present in dict 'kw', coerce its value to type 'type\_' if
    necessary.  If 'flexi_bool' is True, the string '0' is considered false
    when coercing to boolean.
    """

    if dest is None:
        dest = kw

    if (
        key in kw
        and (not isinstance(type_, type) or not isinstance(kw[key], type_))
        and kw[key] is not None
    ):
        if type_ is bool and flexi_bool:
            dest[key] = asbool(kw[key])
        else:
            dest[key] = type_(kw[key])


def constructor_key(obj, cls):
    """Produce a tuple structure that is cacheable using the __dict__ of
    obj to retrieve values

    """
    names = get_cls_kwargs(cls)
    return (cls,) + tuple(
        (k, obj.__dict__[k]) for k in names if k in obj.__dict__
    )


def constructor_copy(obj, cls, *args, **kw):
    """Instantiate cls using the __dict__ of obj as constructor arguments.

    Uses inspect to match the named arguments of ``cls``.

    """

    names = get_cls_kwargs(cls)
    kw.update(
        (k, obj.__dict__[k]) for k in names.difference(kw) if k in obj.__dict__
    )
    return cls(*args, **kw)


def counter():
    """Return a threadsafe counter function."""

    lock = compat.threading.Lock()
    counter = itertools.count(1)

    # avoid the 2to3 "next" transformation...
    def _next():
        with lock:
            return next(counter)

    return _next


def duck_type_collection(specimen, default=None):
    """Given an instance or class, guess if it is or is acting as one of
    the basic collection types: list, set and dict.  If the __emulates__
    property is present, return that preferentially.
    """

    if hasattr(specimen, "__emulates__"):
        # canonicalize set vs sets.Set to a standard: the builtin set
        if specimen.__emulates__ is not None and issubclass(
            specimen.__emulates__, set
        ):
            return set
        else:
            return specimen.__emulates__

    isa = isinstance(specimen, type) and issubclass or isinstance
    if isa(specimen, list):
        return list
    elif isa(specimen, set):
        return set
    elif isa(specimen, dict):
        return dict

    if hasattr(specimen, "append"):
        return list
    elif hasattr(specimen, "add"):
        return set
    elif hasattr(specimen, "set"):
        return dict
    else:
        return default


def assert_arg_type(arg, argtype, name):
    if isinstance(arg, argtype):
        return arg
    else:
        if isinstance(argtype, tuple):
            raise exc.ArgumentError(
                "Argument '%s' is expected to be one of type %s, got '%s'"
                % (name, " or ".join("'%s'" % a for a in argtype), type(arg))
            )
        else:
            raise exc.ArgumentError(
                "Argument '%s' is expected to be of type '%s', got '%s'"
                % (name, argtype, type(arg))
            )


def dictlike_iteritems(dictlike):
    """Return a (key, value) iterator for almost any dict-like object."""

    if compat.py3k:
        if hasattr(dictlike, "items"):
            return list(dictlike.items())
    else:
        if hasattr(dictlike, "iteritems"):
            return dictlike.iteritems()
        elif hasattr(dictlike, "items"):
            return iter(dictlike.items())

    getter = getattr(dictlike, "__getitem__", getattr(dictlike, "get", None))
    if getter is None:
        raise TypeError("Object '%r' is not dict-like" % dictlike)

    if hasattr(dictlike, "iterkeys"):

        def iterator():
            for key in dictlike.iterkeys():
                yield key, getter(key)

        return iterator()
    elif hasattr(dictlike, "keys"):
        return iter((key, getter(key)) for key in dictlike.keys())
    else:
        raise TypeError("Object '%r' is not dict-like" % dictlike)


class classproperty(property):
    """A decorator that behaves like @property except that operates
    on classes rather than instances.

    The decorator is currently special when using the declarative
    module, but note that the
    :class:`~.sqlalchemy.ext.declarative.declared_attr`
    decorator should be used for this purpose with declarative.

    """

    def __init__(self, fget, *arg, **kw):
        super(classproperty, self).__init__(fget, *arg, **kw)
        self.__doc__ = fget.__doc__

    def __get__(desc, self, cls):
        return desc.fget(cls)


class hybridproperty(object):
    def __init__(self, func):
        self.func = func
        self.clslevel = func

    def __get__(self, instance, owner):
        if instance is None:
            clsval = self.clslevel(owner)
            return clsval
        else:
            return self.func(instance)

    def classlevel(self, func):
        self.clslevel = func
        return self


class hybridmethod(object):
    """Decorate a function as cls- or instance- level."""

    def __init__(self, func):
        self.func = self.__func__ = func
        self.clslevel = func

    def __get__(self, instance, owner):
        if instance is None:
            return self.clslevel.__get__(owner, owner.__class__)
        else:
            return self.func.__get__(instance, owner)

    def classlevel(self, func):
        self.clslevel = func
        return self


class _symbol(int):
    def __new__(self, name, doc=None, canonical=None):
        """Construct a new named symbol."""
        assert isinstance(name, compat.string_types)
        if canonical is None:
            canonical = hash(name)
        v = int.__new__(_symbol, canonical)
        v.name = name
        if doc:
            v.__doc__ = doc
        return v

    def __reduce__(self):
        return symbol, (self.name, "x", int(self))

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return "symbol(%r)" % self.name


_symbol.__name__ = "symbol"


class symbol(object):
    """A constant symbol.

    >>> symbol('foo') is symbol('foo')
    True
    >>> symbol('foo')
    <symbol 'foo>

    A slight refinement of the MAGICCOOKIE=object() pattern.  The primary
    advantage of symbol() is its repr().  They are also singletons.

    Repeated calls of symbol('name') will all return the same instance.

    The optional ``doc`` argument assigns to ``__doc__``.  This
    is strictly so that Sphinx autoattr picks up the docstring we want
    (it doesn't appear to pick up the in-module docstring if the datamember
    is in a different module - autoattribute also blows up completely).
    If Sphinx fixes/improves this then we would no longer need
    ``doc`` here.

    """

    symbols = {}
    _lock = compat.threading.Lock()

    def __new__(cls, name, doc=None, canonical=None):
        with cls._lock:
            sym = cls.symbols.get(name)
            if sym is None:
                cls.symbols[name] = sym = _symbol(name, doc, canonical)
            return sym

    @classmethod
    def parse_user_argument(
        cls, arg, choices, name, resolve_symbol_names=False
    ):
        """Given a user parameter, parse the parameter into a chosen symbol.

        The user argument can be a string name that matches the name of a
        symbol, or the symbol object itself, or any number of alternate choices
        such as True/False/ None etc.

        :param arg: the user argument.
        :param choices: dictionary of symbol object to list of possible
         entries.
        :param name: name of the argument.   Used in an :class:`.ArgumentError`
         that is raised if the parameter doesn't match any available argument.
        :param resolve_symbol_names: include the name of each symbol as a valid
         entry.

        """
        # note using hash lookup is tricky here because symbol's `__hash__`
        # is its int value which we don't want included in the lookup
        # explicitly, so we iterate and compare each.
        for sym, choice in choices.items():
            if arg is sym:
                return sym
            elif resolve_symbol_names and arg == sym.name:
                return sym
            elif arg in choice:
                return sym

        if arg is None:
            return None

        raise exc.ArgumentError("Invalid value for '%s': %r" % (name, arg))


_creation_order = 1


def set_creation_order(instance):
    """Assign a '_creation_order' sequence to the given instance.

    This allows multiple instances to be sorted in order of creation
    (typically within a single thread; the counter is not particularly
    threadsafe).

    """
    global _creation_order
    instance._creation_order = _creation_order
    _creation_order += 1


def warn_exception(func, *args, **kwargs):
    """executes the given function, catches all exceptions and converts to
    a warning.

    """
    try:
        return func(*args, **kwargs)
    except Exception:
        warn("%s('%s') ignored" % sys.exc_info()[0:2])


def ellipses_string(value, len_=25):
    try:
        if len(value) > len_:
            return "%s..." % value[0:len_]
        else:
            return value
    except TypeError:
        return value


class _hash_limit_string(compat.text_type):
    """A string subclass that can only be hashed on a maximum amount
    of unique values.

    This is used for warnings so that we can send out parameterized warnings
    without the __warningregistry__ of the module,  or the non-overridable
    "once" registry within warnings.py, overloading memory,


    """

    def __new__(cls, value, num, args):
        interpolated = (value % args) + (
            " (this warning may be suppressed after %d occurrences)" % num
        )
        self = super(_hash_limit_string, cls).__new__(cls, interpolated)
        self._hash = hash("%s_%d" % (value, hash(interpolated) % num))
        return self

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        return hash(self) == hash(other)


def warn(msg, code=None):
    """Issue a warning.

    If msg is a string, :class:`.exc.SAWarning` is used as
    the category.

    """
    if code:
        _warnings_warn(exc.SAWarning(msg, code=code))
    else:
        _warnings_warn(msg, exc.SAWarning)


def warn_limited(msg, args):
    """Issue a warning with a parameterized string, limiting the number
    of registrations.

    """
    if args:
        msg = _hash_limit_string(msg, 10, args)
    _warnings_warn(msg, exc.SAWarning)


def _warnings_warn(message, category=None, stacklevel=2):

    # adjust the given stacklevel to be outside of SQLAlchemy
    try:
        frame = sys._getframe(stacklevel)
    except ValueError:
        # being called from less than 3 (or given) stacklevels, weird,
        # but don't crash
        stacklevel = 0
    except:
        # _getframe() doesn't work, weird interpreter issue, weird,
        # ok, but don't crash
        stacklevel = 0
    else:
        # using __name__ here requires that we have __name__ in the
        # __globals__ of the decorated string functions we make also.
        # we generate this using {"__name__": fn.__module__}
        while frame is not None and re.match(
            r"^(?:sqlalchemy\.|alembic\.)", frame.f_globals.get("__name__", "")
        ):
            frame = frame.f_back
            stacklevel += 1

    if category is not None:
        warnings.warn(message, category, stacklevel=stacklevel + 1)
    else:
        warnings.warn(message, stacklevel=stacklevel + 1)


def only_once(fn, retry_on_exception):
    """Decorate the given function to be a no-op after it is called exactly
    once."""

    once = [fn]

    def go(*arg, **kw):
        # strong reference fn so that it isn't garbage collected,
        # which interferes with the event system's expectations
        strong_fn = fn  # noqa
        if once:
            once_fn = once.pop()
            try:
                return once_fn(*arg, **kw)
            except:
                if retry_on_exception:
                    once.insert(0, once_fn)
                raise

    return go


_SQLA_RE = re.compile(r"sqlalchemy/([a-z_]+/){0,2}[a-z_]+\.py")
_UNITTEST_RE = re.compile(r"unit(?:2|test2?/)")


def chop_traceback(tb, exclude_prefix=_UNITTEST_RE, exclude_suffix=_SQLA_RE):
    """Chop extraneous lines off beginning and end of a traceback.

    :param tb:
      a list of traceback lines as returned by ``traceback.format_stack()``

    :param exclude_prefix:
      a regular expression object matching lines to skip at beginning of
      ``tb``

    :param exclude_suffix:
      a regular expression object matching lines to skip at end of ``tb``
    """
    start = 0
    end = len(tb) - 1
    while start <= end and exclude_prefix.search(tb[start]):
        start += 1
    while start <= end and exclude_suffix.search(tb[end]):
        end -= 1
    return tb[start : end + 1]


NoneType = type(None)


def attrsetter(attrname):
    code = "def set(obj, value):" "    obj.%s = value" % attrname
    env = locals().copy()
    exec(code, env)
    return env["set"]


class EnsureKWArgType(type):
    r"""Apply translation of functions to accept \**kw arguments if they
    don't already.

    """

    def __init__(cls, clsname, bases, clsdict):
        fn_reg = cls.ensure_kwarg
        if fn_reg:
            for key in clsdict:
                m = re.match(fn_reg, key)
                if m:
                    fn = clsdict[key]
                    spec = compat.inspect_getfullargspec(fn)
                    if not spec.varkw:
                        clsdict[key] = wrapped = cls._wrap_w_kw(fn)
                        setattr(cls, key, wrapped)
        super(EnsureKWArgType, cls).__init__(clsname, bases, clsdict)

    def _wrap_w_kw(self, fn):
        def wrap(*arg, **kw):
            return fn(*arg)

        return update_wrapper(wrap, fn)


def wrap_callable(wrapper, fn):
    """Augment functools.update_wrapper() to work with objects with
    a ``__call__()`` method.

    :param fn:
      object with __call__ method

    """
    if hasattr(fn, "__name__"):
        return update_wrapper(wrapper, fn)
    else:
        _f = wrapper
        _f.__name__ = fn.__class__.__name__
        if hasattr(fn, "__module__"):
            _f.__module__ = fn.__module__

        if hasattr(fn.__call__, "__doc__") and fn.__call__.__doc__:
            _f.__doc__ = fn.__call__.__doc__
        elif fn.__doc__:
            _f.__doc__ = fn.__doc__

        return _f


def quoted_token_parser(value):
    """Parse a dotted identifier with accommodation for quoted names.

    Includes support for SQL-style double quotes as a literal character.

    E.g.::

        >>> quoted_token_parser("name")
        ["name"]
        >>> quoted_token_parser("schema.name")
        ["schema", "name"]
        >>> quoted_token_parser('"Schema"."Name"')
        ['Schema', 'Name']
        >>> quoted_token_parser('"Schema"."Name""Foo"')
        ['Schema', 'Name""Foo']

    """

    if '"' not in value:
        return value.split(".")

    # 0 = outside of quotes
    # 1 = inside of quotes
    state = 0
    result = [[]]
    idx = 0
    lv = len(value)
    while idx < lv:
        char = value[idx]
        if char == '"':
            if state == 1 and idx < lv - 1 and value[idx + 1] == '"':
                result[-1].append('"')
                idx += 1
            else:
                state ^= 1
        elif char == "." and state == 0:
            result.append([])
        else:
            result[-1].append(char)
        idx += 1

    return ["".join(token) for token in result]


def add_parameter_text(params, text):
    params = _collections.to_list(params)

    def decorate(fn):
        doc = fn.__doc__ is not None and fn.__doc__ or ""
        if doc:
            doc = inject_param_text(doc, {param: text for param in params})
        fn.__doc__ = doc
        return fn

    return decorate


def _dedent_docstring(text):
    split_text = text.split("\n", 1)
    if len(split_text) == 1:
        return text
    else:
        firstline, remaining = split_text
    if not firstline.startswith(" "):
        return firstline + "\n" + textwrap.dedent(remaining)
    else:
        return textwrap.dedent(text)


def inject_docstring_text(doctext, injecttext, pos):
    doctext = _dedent_docstring(doctext or "")
    lines = doctext.split("\n")
    if len(lines) == 1:
        lines.append("")
    injectlines = textwrap.dedent(injecttext).split("\n")
    if injectlines[0]:
        injectlines.insert(0, "")

    blanks = [num for num, line in enumerate(lines) if not line.strip()]
    blanks.insert(0, 0)

    inject_pos = blanks[min(pos, len(blanks) - 1)]

    lines = lines[0:inject_pos] + injectlines + lines[inject_pos:]
    return "\n".join(lines)


_param_reg = re.compile(r"(\s+):param (.+?):")


def inject_param_text(doctext, inject_params):
    doclines = collections.deque(doctext.splitlines())
    lines = []

    # TODO: this is not working for params like ":param case_sensitive=True:"

    to_inject = None
    while doclines:
        line = doclines.popleft()

        m = _param_reg.match(line)

        if to_inject is None:
            if m:
                param = m.group(2).lstrip("*")
                if param in inject_params:
                    # default indent to that of :param: plus one
                    indent = " " * len(m.group(1)) + " "

                    # but if the next line has text, use that line's
                    # indentation
                    if doclines:
                        m2 = re.match(r"(\s+)\S", doclines[0])
                        if m2:
                            indent = " " * len(m2.group(1))

                    to_inject = indent + inject_params[param]
        elif m:
            lines.extend(["\n", to_inject, "\n"])
            to_inject = None
        elif not line.rstrip():
            lines.extend([line, to_inject, "\n"])
            to_inject = None
        elif line.endswith("::"):
            # TODO: this still wont cover if the code example itself has blank
            # lines in it, need to detect those via indentation.
            lines.extend([line, doclines.popleft()])
            continue
        lines.append(line)

    return "\n".join(lines)


def repr_tuple_names(names):
    """Trims a list of strings from the middle and return a string of up to
    four elements. Strings greater than 11 characters will be truncated"""
    if len(names) == 0:
        return None
    flag = len(names) <= 4
    names = names[0:4] if flag else names[0:3] + names[-1:]
    res = ["%s.." % name[:11] if len(name) > 11 else name for name in names]
    if flag:
        return ", ".join(res)
    else:
        return "%s, ..., %s" % (", ".join(res[0:3]), res[-1])


def has_compiled_ext():
    try:
        from sqlalchemy import cimmutabledict  # noqa: F401
        from sqlalchemy import cprocessors  # noqa: F401
        from sqlalchemy import cresultproxy  # noqa: F401

        return True
    except ImportError:
        return False
