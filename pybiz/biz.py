import re
import os

from abc import ABCMeta, abstractmethod
from types import MethodType

from .patch import JsonPatchMixin
from .dao import DaoManager
from .dirty import DirtyDict, DirtyInterface
from .util import is_bizobj
from .schema import Field
from .const import (
    PRE_PATCH_ANNOTATION,
    POST_PATCH_ANNOTATION,
    PATCH_PATH_ANNOTATION,
    PATCH_ANNOTATION,
    IS_BIZOBJ_ANNOTATION,
    )

"""
Relationship Building Strategy:
    Load:
        - If any relationship name matches a schema field name
          of type <List> or <Nested>, try to load the raw data
          into relationship data.
    Dump:
        - Simply dump the related objects into the data dict
          returned from the schema dump.

"""


class Relationship(object):

    def __init__(self, bizobj_class, many=False, dump_to=None, load_from=None):
        self.bizobj_class = bizobj_class
        self.load_from = load_from
        self.dump_to = dump_to
        self.many = many
        self.name = None


class BizObjectMeta(ABCMeta):

    class RelationshipsMixin(object):
        def __init__(self, *args, **kwargs):
            self._relationship_data = {}

    def __new__(cls, name, bases, dict_):
        bases = bases + (cls.RelationshipsMixin,)

        # set this attribute in order to be able to
        # use duck typing to check isinstance of BizObjects
        dict_[IS_BIZOBJ_ANNOTATION] = True

        return ABCMeta.__new__(cls, name, bases, dict_)

    def __init__(cls, name, bases, dict_):
        bases = bases + (cls.RelationshipsMixin,)
        ABCMeta.__init__(cls, name, bases + (cls.RelationshipsMixin,), dict_)

        relationships = cls.build_relationships()
        cls._relationships = relationships

        # build field properties according to the schema
        # associated with this BizObject class
        schema_factory = cls.schema()
        if schema_factory is not None:
            s = cls._schema = schema_factory()
            s.strict = True
            if s is not None:
                cls.build_properties(s, relationships)

        # JsonPatchMixin integration:
        # register pre and post patch callbacks
        if any(issubclass(x, JsonPatchMixin) for x in bases):
            # scan class methods for those annotated as patch hooks
            # and register them as such.
            for k in dir(cls):
                v = getattr(cls, k)
                if isinstance(v, MethodType):
                    path = getattr(v, PATCH_PATH_ANNOTATION, None)
                    if hasattr(v, PRE_PATCH_ANNOTATION):
                        assert path
                        cls.add_pre_patch_hook(path, k)
                    elif hasattr(v, PATCH_ANNOTATION):
                        assert path
                        cls.set_patch_hook(path, k)
                    elif hasattr(v, POST_PATCH_ANNOTATION):
                        assert path
                        cls.add_post_patch_hook(path, k)

    def build_relationships(cls):
        # aggregate all relationships delcared on the bizobj
        # class into a single "relationships" dict.
        relationships = {}
        for k in dir(cls):
            v = getattr(cls, k)
            if isinstance(v, Relationship):
                relationships[k] = v
                v.name = k

        # clear the individually declared relationships out of
        # class namespace.
        for k in relationships:
            delattr(cls, k)

        return relationships

    def build_properties(cls, schema, relationships: dict):
        """
        Create properties out of the fields declared on the schema associated
        with the class.
        """
        def build_property(k):
            def fget(self):
                return self[k]

            def fset(self, value):
                self[k] = value

            def fdel(self):
                del self[k]

            return property(fget=fget, fset=fset, fdel=fdel)

        def build_rel_property(k, rel):
            def fget(self):
                return self._relationship_data.get(k)

            def fset(self, value):
                rel = self._relationships[k]
                is_sequence = isinstance(value, (list, tuple, set))
                if not is_sequence:
                    if rel.many:
                        raise ValueError('{} must be non-scalar'.format(k))
                    bizobj_list = value
                    self._relationship_data[k] = bizobj_list
                elif is_sequence:
                    if not rel.many:
                        raise ValueError('{} must be scalar'.format(k))
                    self._relationship_data[k] = value

            def fdel(self):
                del self._relationship_data[k]

            return property(fget=fget, fset=fset, fdel=fdel)

        for rel_name, rel in relationships.items():
            assert not hasattr(cls, rel_name)
            setattr(cls, rel_name, build_rel_property(rel_name, rel))

        for field_name in schema.fields:
            if field_name not in relationships:
                assert not hasattr(cls, field_name)
                setattr(cls, field_name, build_property(field_name))


class BizObject(DirtyInterface, JsonPatchMixin, metaclass=BizObjectMeta):

    _schema = None  # set by metaclass
    _relationships = None  # set by metaclass
    _dao_manager = DaoManager.get_instance()

    def __init__(self, data=None, **kwargs_data):
        super(BizObject, self).__init__()
        self._data = self._load(data, kwargs_data)
        self._public_id = None
        self._bizobj_id = None

        if self._schema is not None:
            self._is_id_in_schema = '_id' in self._schema.fields
            self._is_public_id_in_schema = 'public_id' in self._schema.fields
        else:
            self._is_id_in_schema = False
            self._is_public_id_in_schema = False

    def __getitem__(self, key):
        if key in self._data:
            return self._data[key]
        elif key in self._relationships:
            return self._relationships[key].data
        elif self._schema and key in self._schema.fields:
            return None

        raise KeyError(key)

    def __setitem__(self, key, value):
        if key in self._relationships:
            rel = self._relationships[key]
            is_sequence = isinstance(value, (list, tuple, set))
            if rel.many:
                assert is_sequence
            else:
                assert not is_sequence
            rel.data = list(value)

        if self._schema is not None:
            if key not in self._schema.fields:
                raise KeyError('{} not in {} schema'.format(
                        key, self._schema.__class__.__name__))

        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def __repr__(self):
        bizobj_id = ''
        _id = self._id
        if _id is not None:
            bizobj_id = '/id={}'.format(_id)
        else:
            public_id = self.public_id
            if public_id is not None:
                bizobj_id = '/public_id={}'.format(public_id)

        dirty_flag = '*' if self._data.dirty else ''

        return '<{class_name}{dirty_flag}{bizobj_id}>'.format(
                class_name=self.__class__.__name__,
                bizobj_id=bizobj_id,
                dirty_flag=dirty_flag)

    @classmethod
    @abstractmethod
    def schema(cls):
        return None

    @classmethod
    def dao_provider(cls):
        """
        By default, we try to read the dao_provider string from an environment
        variable named X_DAO_PROVIDER, where X is the uppercase name of this
        class. Otherwise, we try to read a default global dao provider from the
        DAO_PROVIDER environment variable.
        """
        cls_name = re.sub(r'([a-z])([A-Z0-9])', r'\1_\2', cls.__name__).upper()
        dao_provider = os.environ.get('{}_DAO_PROVIDER'.format(cls_name))
        return dao_provider or os.environ['DAO_PROVIDER']

    @classmethod
    def get_dao(cls):
        return cls._dao_manager.get_dao_for_bizobj(cls)

    @property
    def data(self):
        return self._data

    @property
    def relationships(self):
        return self._relationship_data

    @property
    def dao(self):
        return self._dao_manager.get_dao_for_bizobj(self.__class__)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def update(self, dct):
        self._data.update(dct)

    def dump(self):
        """
        Dump the fields of this business object along with its related objects
        (declared as relationships) to a plain ol' dict.
        """
        data = self._dump_schema()
        related_data = self._dump_relationships()
        data.update(related_data)
        return data

    def _dump_schema(self):
        """
        Dump all scalar fields of the instance to a dict.
        """
        if self._schema is not None:
            return self._schema.dump(self._data).data
        return self._data.copy()

    def _dump_relationships(self):
        """
        If no schema is associated with the instance, we dump all relationship
        data that exists. Otherwise, we only dump data declared as corresponding
        fields in the schema.
        """
        data = {}
        for rel_name, rel_val in self.relationships.items():
            rel = self._relationships[rel_name]
            load_from_field = rel.load_from or rel_name
            has_field = load_from_field in self._schema.fields
            if not self._schema or (load_from_field in self._schema.fields):
                dump_to = rel.dump_to or rel_name
                data[dump_to] = rel_val.dump()
        return data

    def _load(self, data, kwargs_data):
        """
        Load data passed into the bizobj ctor into an internal DirtyDict. If any
        of the data fields correspond with delcared Relationships, load the
        bizobjs declared by said Relationships from said data.
        """
        data = data or {}
        data.update(kwargs_data)

        # TODO: if bizobjs are passed in to ctor but not declared as
        # relationships, raise exception

        # eagerly load all related bizobjs from the loaded data dict,
        # removing the fields from said dict.
        # TODO: get rel_name from rel.name instead
        for rel_name, rel in self._relationships.items():
            if rel_name in self._schema.fields:
                load_from = rel.load_from or rel_name
                related_data = data.pop(load_from, None)
                if related_data is not None:
                    if rel.many:
                        related_bizobj_list = [
                            rel.bizobj_class(_) for _ in related_data
                            if (not is_bizobj(_))
                                and isinstance(_, rel.bizobj_class)
                            ]
                        self._relationship_data[rel_name] = related_bizobj_list
                    else:
                        if not is_bizobj(related_data):
                            import ipdb; ipdb.set_trace()
                            related_bizobj = rel.bizobj_class(related_data)
                        else:
                            related_bizobj = related_data
                        self._relationship_data[rel_name] = related_bizobj

        if self._schema is not None:
            result = self._schema.load(data)
            if result.errors:
                raise Exception(str(result.errors))
            data = result.data

        # at this point, the data dict has been cleared of any fields that are
        # shadowed by Relationships declared on the bizobj class.
        return DirtyDict(data)

    @property
    def dirty(self):
        return self._data.dirty

    def set_parent(self, key_in_parent, parent):
        self._data.set_parent(key_in_parent, parent)

    def has_parent(self, obj):
        return self._data.has_parent(obj)

    def get_parent(self):
        return self._data.get_parent()

    def mark_dirty(self, key):
        self._data.mark_dirty(key)

    def clear_dirty(self, keys=None):
        self._data.clear_dirty(keys=keys)

    def save(self, fetch=False):
        nested_bizobjs = []
        data_to_save = {}

        # depth-first save nested bizobjs.
        for k, v in self.relationships.items():
            if not v:
                continue
            rel = self._relationships[k]
            if rel.many:
                dump_data_list = []
                # TODO keep track of which are dirty to avoid O(N) scan of list
                for bizobj in v:
                    if bizobj.dirty:
                        bizobj.save()
                        dump_data_list.append(bizobj.dump())
                if dump_data_list:
                    data_to_save[k] = data_to_save
            elif v.dirty:
                v.save()
                data_to_save[k] = v.dump()

        for k in self._data.dirty:
            data_to_save[k] = self[k]

        # persist data and refresh data
        if data_to_save:
            _id = self.dao.save(data_to_save, _id=self._id)
            self._id = _id
            if fetch:
                self.update(self.dao.fetch(_id=_id))
            self.clear_dirty()
