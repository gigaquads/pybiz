import os
import inspect
import importlib
import traceback

import venusian
import yaml

from collections import defaultdict
from threading import local
from appyratus.validation import Schema, fields

from pybiz.dao.base import Dao
from pybiz.manifest import Manifest
from pybiz.exc import ApiError


class FunctionRegistry(object):
    def __init__(self, manifest=None):
        self.thread_local = local()
        self._manifest = manifest
        self._bootstrapped = False
        self._decorators = []

    def __call__(
        self,
        on_decorate=None,
        on_request=None,
        on_response=None,
        *args,
        **kwargs
    ):
        """
        Use this to decorate functions, adding them to this FunctionRegistry.
        Each time a function is decorated, it arives at the "on_decorate"
        method, where you can registry the function with a web framework or
        whatever system you have in mind.

        Usage:

        ```python3
            api = FunctionRegistry()

            @api()
            def do_something():
                pass
        ```
        """
        decorator = self.function_decorator_type(
            self,
            on_decorate=on_decorate or self.on_decorate,
            on_request=on_request or self.on_request,
            on_response=on_response or self.on_response,
            *args, **kwargs
        )
        self._decorators.append(decorator)
        return decorator

    @property
    def function_decorator_type(self):
        return FunctionDecorator

    @property
    def function_proxy_type(self):
        return FunctionProxy

    @property
    def manifest(self):
        return self._manifest

    @property
    def bootstrapped(self):
        return self._bootstrapped

    def bootstrap(self, filepath: str=None):
        """
        Bootstrap the data, business, and service layers, wiring them up,
        according to the settings contained in a service manifest file.

        Args:
            - filepath: Path to manifest.yml file
        """
        if self._bootstrapped:
            return
        self._bootstrapped = True
        if self._manifest is None or filepath is not None:
            self._manifest = Manifest(self, filepath=filepath)
        if self._manifest is not None:
            self._manifest.process()

    def start(self, *args, **kwargs):
        """
        Enter the main loop in whatever program context your FunctionRegistry is
        being used, like in a web framework or a REPL.
        """
        raise NotImplementedError('override in subclass')

    def on_decorate(self, proxy: 'FunctionProxy'):
        """
        We come here whenever a function is decorated by this registry. Here we
        can add the decorated function to, say, a web framework as a route.
        """

    def on_request(self, signature, *args, **kwargs):
        """
        This executes immediately before calling a registered function. You
        must return re-packaged args and kwargs here. However, if nothing is
        returned, the raw args and kwargs are used.
        """
        return (args, kwargs)

    def on_response(self, result, *args, **kwargs):
        """
        The return value of registered callables come here as `result`. Here
        any global post-processing can be done. Args and kwargs consists of
        whatever raw data was passed into the callable *before* on_request
        executed.
        """
        return result


class FunctionDecorator(object):
    def __init__(self,
        registry,
        on_decorate=None,
        on_request=None,
        on_response=None,
        **params
    ):
        self.registry = registry
        self.on_decorate = on_decorate
        self.on_request = on_request
        self.on_response = on_response
        self.params = params

    def __call__(self, func):
        proxy = self.registry.function_proxy_type(func, self)
        if self.on_decorate is not None:
            self.on_decorate(proxy)
        return proxy


class FunctionProxy(object):
    def __init__(self, func, decorator):
        self.func = func
        self.signature = inspect.signature(self.func)
        self.decorator = decorator

    def __repr__(self):
        return '<FunctionProxy({})>'.format(', '.join([
                'method={}'.format(self.func.__name__)
            ]))

    def __call__(self, *args, **kwargs):
        on_request = self.decorator.on_request
        on_request_retval = on_request(self.signature, *args, **kwargs)
        if on_request_retval:
            prepared_args, prepared_kwargs = on_request_retval
        else:
            prepared_args, prepared_kwargs = args, kwargs
        result = self.func(*prepared_args, **prepared_kwargs)
        self.decorator.on_response(result, *args, **kwargs)
        return result

    @property
    def func_name(self):
        return self.func.__name__ if self.func else None