from typing import Dict, List, Type, Set, Text

from pybiz.dao import Dao
from pybiz.util import is_sequence


class DaoBinding(object):
    def __init__(self, biz_type, dao_instance, dao_bind_kwargs=None):
        self.biz_type = biz_type
        self.dao_instance = dao_instance
        self.dao_bind_kwargs = dao_bind_kwargs or {}
        self._is_bound = False

    def __repr__(self):
        return f'<DaoBinding({self.biz_type_name}, {self.dao_type_name})>'

    def bind(self):
        self.dao_instance.bind(self.biz_type, **self.dao_bind_kwargs)
        self._is_bound = True

    @property
    def is_bound(self):
        return self._is_bound

    @property
    def dao_type(self):
        return self.dao_instance.__class__

    @property
    def dao_type_name(self):
        return self.dao_type.__name__

    @property
    def biz_type_name(self):
        return self.biz_type.__name__


class DaoBinder(object):
    """
    Stores and manages a global registry, entailing which BizObject class is
    associated with which Dao class.
    """

    def __init__(self):
        self._bindings = {}
        self._named_dao_types = {}

    @classmethod
    def get_instance(cls):
        """
        Get the global singleton instance.
        """
        attr_name = '_instance'
        singleton = getattr(cls, attr_name, None)
        if singleton is None:
            singleton = cls()
            setattr(cls, attr_name, singleton)
        return singleton

    @property
    def bindings(self):
        return list(self._bindings.values())

    def register(
        self,
        biz_type: Type['BizObject'],
        dao_type: Type[Dao],
        dao_bind_kwargs: Dict = None,
    ):
        biz_type_name = biz_type.__name__
        dao_type_name = dao_type.__name__

        if dao_type_name not in self._named_dao_types:
            dao_type = type(dao_type_name, (dao_type, ), {})
            self._named_dao_types[dao_type_name] = dao_type

        dao_instance = dao_type()
        biz_type.binder = self

        self._bindings[biz_type_name] = binding = DaoBinding(
            biz_type=biz_type,
            dao_instance=dao_instance,
            dao_bind_kwargs=dao_bind_kwargs,
        )
        return binding

    def bind(self, biz_types: Set[Type['BizObject']] = None):
        if not biz_types:
            biz_types = [v.biz_type for v in self._bindings.values()]
        elif not is_sequence(biz_types):
            biz_types = [biz_types]
        for biz_type in biz_types:
            biz_type.binder = self  # this is used in BizObject.get_dao()
            self.get_dao_instance(biz_type)

    def get_dao_type_by_name(dao_type_name: Text) -> Type[Dao]:
        return self._named_dao_types[dao_type_name]

    def get_dao_instance(self, biz_type: Type['BizObject'], bind=True) -> Dao:
        if isinstance(biz_type, str):
            binding = self._bindings.get(biz_type)
        else:
            binding = self._bindings.get(biz_type.__name__)

        if binding is None:
            # lazily register a new binding
            base_dao_type = biz_type.__dao__()
            binding = self.register(biz_type, base_dao_type)

        # call bind only if it already hasn't been called
        if bind and (not binding.is_bound):
            binding.bind()

        return binding.dao_instance

    def is_registered(self, biz_type: Type['BizObject']) -> bool:
        if isinstance(biz_type, str):
            return biz_type in self._bindings
        else:
            return biz_type.__name__ in self._bindings

    def is_bound(self, biz_type: Type['BizObject']) -> bool:
        if isinstance(biz_type, str):
            return self._bindings[biz_type].is_bound
        else:
            return self._bindings[biz_type.__name__].is_bound
