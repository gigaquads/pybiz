import inspect

from typing import Dict, Tuple, Set, Type

from appyratus.memoize import memoized_property


class RegistryMiddleware(object):

    def __repr__(self):
        return f'<Middleware({self.__class__.__name__})>'

    @memoized_property
    def registry_types(self) -> Tuple[Type['Registry']]:
        """
        Return a tuple of Registry class objects for which this middleware
        applies.
        """
        from pybiz.api.registry import Registry

        return (Registry, )

    def pre_request(self, proxy: 'RegistryProxy', args: Tuple, kwargs: Dict):
        """
        In pre_request, args and kwargs are in the raw form before being
        processed by registry.on_request.
        """

    def on_request(self, proxy: 'RegistryProxy', args: Tuple, kwargs: Dict):
        """
        In on_request, args and kwargs are in the form output by
        registry.on_request.
        """

    def post_request(self, proxy: 'RegistryObject', args: Tuple, kwargs: Dict, result):
        """
        In post_request, args and kwargs are in the form output by
        registry.on_request.
        """
