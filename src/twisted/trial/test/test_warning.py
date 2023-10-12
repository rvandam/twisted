# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for Trial's interaction with the Python warning system.
"""
from __future__ import annotations

import sys
import warnings
from io import StringIO
from typing import Mapping, Sequence, TypeVar
from unittest import TestResult

from twisted.python.filepath import FilePath
from twisted.trial._synctest import (
    _collectWarnings,
    _setWarningRegistryToNone,
    _Warning,
)
from twisted.trial.unittest import SynchronousTestCase


class Mask:
    """
    Hide a test case definition from trial's automatic discovery mechanism.
    """

    class MockTests(SynchronousTestCase):
        """
        A test case which is used by L{FlushWarningsTests} to verify behavior
        which cannot be verified by code inside a single test method.
        """

        message = "some warning text"
        category: type[Warning] = UserWarning

        def test_unflushed(self) -> None:
            """
            Generate a warning and don't flush it.
            """
            warnings.warn(self.message, self.category)

        def test_flushed(self) -> None:
            """
            Generate a warning and flush it.
            """
            warnings.warn(self.message, self.category)
            self.assertEqual(len(self.flushWarnings()), 1)


_K = TypeVar("_K")
_V = TypeVar("_V")


class FlushWarningsTests(SynchronousTestCase):
    """
    Tests for C{flushWarnings}, an API for examining the warnings
    emitted so far in a test.
    """

    def assertDictSubset(self, set: Mapping[_K, _V], subset: Mapping[_K, _V]) -> None:
        """
        Assert that all the keys present in C{subset} are also present in
        C{set} and that the corresponding values are equal.
        """
        for k, v in subset.items():
            self.assertEqual(set[k], v)

    def assertDictSubsets(
        self, sets: Sequence[Mapping[_K, _V]], subsets: Sequence[Mapping[_K, _V]]
    ) -> None:
        """
        For each pair of corresponding elements in C{sets} and C{subsets},
        assert that the element from C{subsets} is a subset of the element from
        C{sets}.
        """
        self.assertEqual(len(sets), len(subsets))
        for a, b in zip(sets, subsets):
            self.assertDictSubset(a, b)

    def test_none(self) -> None:
        """
        If no warnings are emitted by a test, C{flushWarnings} returns an empty
        list.
        """
        self.assertEqual(self.flushWarnings(), [])

    def test_several(self) -> None:
        """
        If several warnings are emitted by a test, C{flushWarnings} returns a
        list containing all of them.
        """
        firstMessage = "first warning message"
        firstCategory = UserWarning
        warnings.warn(message=firstMessage, category=firstCategory)

        secondMessage = "second warning message"
        secondCategory = RuntimeWarning
        warnings.warn(message=secondMessage, category=secondCategory)

        self.assertDictSubsets(
            self.flushWarnings(),
            [
                {"category": firstCategory, "message": firstMessage},
                {"category": secondCategory, "message": secondMessage},
            ],
        )

    def test_repeated(self) -> None:
        """
        The same warning triggered twice from the same place is included twice
        in the list returned by C{flushWarnings}.
        """
        message = "the message"
        category = RuntimeWarning
        for i in range(2):
            warnings.warn(message=message, category=category)

        self.assertDictSubsets(
            self.flushWarnings(), [{"category": category, "message": message}] * 2
        )

    def test_cleared(self) -> None:
        """
        After a particular warning event has been returned by C{flushWarnings},
        it is not returned by subsequent calls.
        """
        message = "the message"
        category = RuntimeWarning
        warnings.warn(message=message, category=category)
        self.assertDictSubsets(
            self.flushWarnings(), [{"category": category, "message": message}]
        )
        self.assertEqual(self.flushWarnings(), [])

    def test_unflushed(self) -> None:
        """
        Any warnings emitted by a test which are not flushed are emitted to the
        Python warning system.
        """
        result = TestResult()
        case = Mask.MockTests("test_unflushed")
        case.run(result)
        warningsShown = self.flushWarnings([Mask.MockTests.test_unflushed])
        self.assertEqual(warningsShown[0]["message"], "some warning text")
        self.assertIdentical(warningsShown[0]["category"], UserWarning)

        where = type(case).test_unflushed.__code__
        filename = where.co_filename
        # If someone edits MockTests.test_unflushed, the value added to
        # firstlineno might need to change.
        lineno = where.co_firstlineno + 4

        self.assertEqual(warningsShown[0]["filename"], filename)
        self.assertEqual(warningsShown[0]["lineno"], lineno)

        self.assertEqual(len(warningsShown), 1)

    def test_flushed(self) -> None:
        """
        Any warnings emitted by a test which are flushed are not emitted to the
        Python warning system.
        """
        result = TestResult()
        case = Mask.MockTests("test_flushed")
        output = StringIO()
        monkey = self.patch(sys, "stdout", output)
        case.run(result)
        monkey.restore()
        self.assertEqual(output.getvalue(), "")

    def test_warningsConfiguredAsErrors(self) -> None:
        """
        If a warnings filter has been installed which turns warnings into
        exceptions, tests have an error added to the reporter for them for each
        unflushed warning.
        """

        class CustomWarning(Warning):
            pass

        result = TestResult()
        case = Mask.MockTests("test_unflushed")
        case.category = CustomWarning

        originalWarnings = warnings.filters[:]
        try:
            warnings.simplefilter("error")
            case.run(result)
            self.assertEqual(len(result.errors), 1)
            self.assertIdentical(result.errors[0][0], case)
            self.assertTrue(
                # Different python versions differ in whether they report the
                # fully qualified class name or just the class name.
                result.errors[0][1]
                .splitlines()[-1]
                .endswith("CustomWarning: some warning text")
            )
        finally:
            warnings.filters[:] = originalWarnings  # type: ignore[index]

    def test_flushedWarningsConfiguredAsErrors(self) -> None:
        """
        If a warnings filter has been installed which turns warnings into
        exceptions, tests which emit those warnings but flush them do not have
        an error added to the reporter.
        """

        class CustomWarning(Warning):
            pass

        result = TestResult()
        case = Mask.MockTests("test_flushed")
        case.category = CustomWarning

        originalWarnings = warnings.filters[:]
        try:
            warnings.simplefilter("error")
            case.run(result)
            self.assertEqual(result.errors, [])
        finally:
            warnings.filters[:] = originalWarnings  # type: ignore[index]

    def test_multipleFlushes(self) -> None:
        """
        Any warnings emitted after a call to C{flushWarnings} can be flushed by
        another call to C{flushWarnings}.
        """
        warnings.warn("first message")
        self.assertEqual(len(self.flushWarnings()), 1)
        warnings.warn("second message")
        self.assertEqual(len(self.flushWarnings()), 1)

    def test_filterOnOffendingFunction(self) -> None:
        """
        The list returned by C{flushWarnings} includes only those
        warnings which refer to the source of the function passed as the value
        for C{offendingFunction}, if a value is passed for that parameter.
        """
        firstMessage = "first warning text"
        firstCategory = UserWarning

        def one() -> None:
            warnings.warn(firstMessage, firstCategory, stacklevel=1)

        secondMessage = "some text"
        secondCategory = RuntimeWarning

        def two() -> None:
            warnings.warn(secondMessage, secondCategory, stacklevel=1)

        one()
        two()

        self.assertDictSubsets(
            self.flushWarnings(offendingFunctions=[one]),
            [{"category": firstCategory, "message": firstMessage}],
        )
        self.assertDictSubsets(
            self.flushWarnings(offendingFunctions=[two]),
            [{"category": secondCategory, "message": secondMessage}],
        )

    def test_functionBoundaries(self) -> None:
        """
        Verify that warnings emitted at the very edges of a function are still
        determined to be emitted from that function.
        """

        def warner() -> None:
            warnings.warn("first line warning")
            warnings.warn("internal line warning")
            warnings.warn("last line warning")

        warner()
        self.assertEqual(len(self.flushWarnings(offendingFunctions=[warner])), 3)

    def test_invalidFilter(self) -> None:
        """
        If an object which is neither a function nor a method is included in the
        C{offendingFunctions} list, C{flushWarnings} raises L{ValueError}.  Such
        a call flushes no warnings.
        """
        warnings.warn("oh no")
        self.assertRaises(ValueError, self.flushWarnings, [None])
        self.assertEqual(len(self.flushWarnings()), 1)

    def test_missingSource(self) -> None:
        """
        Warnings emitted by a function the source code of which is not
        available can still be flushed.
        """
        package = FilePath(self.mktemp().encode("utf-8")).child(
            b"twisted_private_helper"
        )
        package.makedirs()
        package.child(b"__init__.py").setContent(b"")
        package.child(b"missingsourcefile.py").setContent(
            b"""
import warnings
def foo():
    warnings.warn("oh no")
"""
        )
        pathEntry = package.parent().path.decode("utf-8")
        sys.path.insert(0, pathEntry)
        self.addCleanup(sys.path.remove, pathEntry)
        from twisted_private_helper import missingsourcefile  # type: ignore[import]

        self.addCleanup(sys.modules.pop, "twisted_private_helper")
        self.addCleanup(sys.modules.pop, missingsourcefile.__name__)
        package.child(b"missingsourcefile.py").remove()

        missingsourcefile.foo()
        self.assertEqual(len(self.flushWarnings([missingsourcefile.foo])), 1)

    def test_renamedSource(self) -> None:
        """
        Warnings emitted by a function defined in a file which has been renamed
        since it was initially compiled can still be flushed.

        This is testing the code which specifically supports working around the
        unfortunate behavior of CPython to write a .py source file name into
        the .pyc files it generates and then trust that it is correct in
        various places.  If source files are renamed, .pyc files may not be
        regenerated, but they will contain incorrect filenames.
        """
        package = FilePath(self.mktemp().encode("utf-8")).child(
            b"twisted_private_helper"
        )
        package.makedirs()
        package.child(b"__init__.py").setContent(b"")
        package.child(b"module.py").setContent(
            b"""
import warnings
def foo():
    warnings.warn("oh no")
"""
        )
        pathEntry = package.parent().path.decode("utf-8")
        sys.path.insert(0, pathEntry)
        self.addCleanup(sys.path.remove, pathEntry)

        # Import it to cause pycs to be generated
        from twisted_private_helper import module

        # Clean up the state resulting from that import; we're not going to use
        # this module, so it should go away.
        del sys.modules["twisted_private_helper"]
        del sys.modules[module.__name__]

        # Some Python versions have extra state related to the just
        # imported/renamed package.  Clean it up too.  See also
        # http://bugs.python.org/issue15912
        try:
            from importlib import invalidate_caches
        except ImportError:
            pass
        else:
            invalidate_caches()

        # Rename the source directory
        package.moveTo(package.sibling(b"twisted_renamed_helper"))

        # Import the newly renamed version
        from twisted_renamed_helper import module  # type: ignore[import]

        self.addCleanup(sys.modules.pop, "twisted_renamed_helper")
        self.addCleanup(sys.modules.pop, module.__name__)

        # Generate the warning
        module.foo()

        # Flush it
        self.assertEqual(len(self.flushWarnings([module.foo])), 1)

    def test_offendingFunctions_deep_branch(self) -> None:
        """
        In Python 3.6 the dis.findlinestarts documented behaviour
        was changed such that the reported lines might not be sorted ascending.
        In Python 3.10 PEP 626 introduced byte-code change such that the last
        line of a function wasn't always associated with the last byte-code.
        In the past flushWarning was not detecting that such a function was
        associated with any warnings.
        """

        def foo(a: int = 1, b: int = 1) -> None:
            if a:
                if b:
                    warnings.warn("oh no")
                else:
                    pass

        # Generate the warning
        foo()

        # Flush it
        self.assertEqual(len(self.flushWarnings([foo])), 1)


class FakeWarning(Warning):
    pass


class CollectWarningsTests(SynchronousTestCase):
    """
    Tests for L{_collectWarnings}.
    """

    def test_callsObserver(self) -> None:
        """
        L{_collectWarnings} calls the observer with each emitted warning.
        """
        firstMessage = "dummy calls observer warning"
        secondMessage = firstMessage[::-1]
        thirdMessage = Warning(1, 2, 3)
        events: list[str | _Warning] = []

        def f() -> None:
            events.append("call")
            warnings.warn(firstMessage)
            warnings.warn(secondMessage)
            warnings.warn(thirdMessage)
            events.append("returning")

        _collectWarnings(events.append, f)

        self.assertEqual(events[0], "call")
        assert isinstance(events[1], _Warning)
        self.assertEqual(events[1].message, firstMessage)
        assert isinstance(events[2], _Warning)
        self.assertEqual(events[2].message, secondMessage)
        assert isinstance(events[3], _Warning)
        self.assertEqual(events[3].message, str(thirdMessage))
        self.assertEqual(events[4], "returning")
        self.assertEqual(len(events), 5)

    def test_suppresses(self) -> None:
        """
        Any warnings emitted by a call to a function passed to
        L{_collectWarnings} are not actually emitted to the warning system.
        """
        output = StringIO()
        self.patch(sys, "stdout", output)
        _collectWarnings(lambda x: None, warnings.warn, "text")
        self.assertEqual(output.getvalue(), "")

    def test_callsFunction(self) -> None:
        """
        L{_collectWarnings} returns the result of calling the callable passed to
        it with the parameters given.
        """
        arguments = []
        value = object()

        def f(*args: object, **kwargs: object) -> object:
            arguments.append((args, kwargs))
            return value

        result = _collectWarnings(lambda x: None, f, 1, "a", b=2, c="d")
        self.assertEqual(arguments, [((1, "a"), {"b": 2, "c": "d"})])
        self.assertIdentical(result, value)

    def test_duplicateWarningCollected(self) -> None:
        """
        Subsequent emissions of a warning from a particular source site can be
        collected by L{_collectWarnings}.  In particular, the per-module
        emitted-warning cache should be bypassed (I{__warningregistry__}).
        """
        # Make sure the worst case is tested: if __warningregistry__ isn't in a
        # module's globals, then the warning system will add it and start using
        # it to avoid emitting duplicate warnings.  Delete __warningregistry__
        # to ensure that even modules which are first imported as a test is
        # running still interact properly with the warning system.
        global __warningregistry__
        del __warningregistry__  # type: ignore[name-defined]

        def f() -> None:
            warnings.warn("foo")

        warnings.simplefilter("default")
        f()
        events: list[_Warning] = []
        _collectWarnings(events.append, f)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].message, "foo")
        self.assertEqual(len(self.flushWarnings()), 1)

    def test_immutableObject(self) -> None:
        """
        L{_collectWarnings}'s behavior is not altered by the presence of an
        object which cannot have attributes set on it as a value in
        C{sys.modules}.
        """
        key = object()
        sys.modules[key] = key  # type: ignore[index, assignment]
        self.addCleanup(sys.modules.pop, key)  # type: ignore[arg-type]
        self.test_duplicateWarningCollected()

    def test_setWarningRegistryChangeWhileIterating(self) -> None:
        """
        If the dictionary passed to L{_setWarningRegistryToNone} changes size
        partway through the process, C{_setWarningRegistryToNone} continues to
        set C{__warningregistry__} to L{None} on the rest of the values anyway.


        This might be caused by C{sys.modules} containing something that's not
        really a module and imports things on setattr.  py.test does this, as
        does L{twisted.python.deprecate.deprecatedModuleAttribute}.
        """
        d: dict[object, A | None] = {}

        class A:
            def __init__(self, key: object) -> None:
                self.__dict__["_key"] = key

            def __setattr__(self, value: object, item: object) -> None:
                d[self._key] = None  # type: ignore[attr-defined]

        key1 = object()
        key2 = object()
        d[key1] = A(key2)

        key3 = object()
        key4 = object()
        d[key3] = A(key4)

        _setWarningRegistryToNone(d)

        # If both key2 and key4 were added, then both A instanced were
        # processed.
        self.assertEqual({key1, key2, key3, key4}, set(d.keys()))
