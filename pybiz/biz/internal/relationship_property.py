import pybiz.biz.biz_object as biz_object

from typing import Text, Type, Tuple

from pybiz.util import is_sequence
from pybiz.predicate import (
    ConditionalPredicate,
    BooleanPredicate,
    OP_CODE,
)
from pybiz.biz.relationship import MockBizObject
from pybiz.exc import RelationshipError

from .query import QuerySpecification
from ..relationship import Relationship
from ..biz_list import BizList


class RelationshipProperty(property):
    def __init__(self, relationship, **kwargs):
        super().__init__(**kwargs)
        self.relationship = relationship

    def __repr__(self):
        if self.relationship is not None:
            return repr(self.relationship).replace(
                'Relationship', 'RelationshipProperty'
            )
        else:
            return '<RelationshipProperty>'

    @classmethod
    def build(cls, relationship: 'Relationship') -> 'RelationshipProperty':
        """
        Build and return a `RelationshipProperty`, that validates the data on
        getting/setting and lazy-loads data on get.
        """
        rel = relationship
        key = relationship.name

        def fget(self):
            """
            Return the related BizObject instance or list.
            """
            if key not in self._related:
                if rel.lazy:
                    # fetch all fields
                    related_obj = rel.query(self)
                    setattr(self, key, related_obj)
                    if rel.on_add is not None:
                        if rel.many:
                            for bizobj in related_obj:
                                rel.on_add(self, bizobj)
                        else:
                            rel.on_add(self, related_obj)

            default = self.BizList([], rel, self) if rel.many else None
            value = self._related.get(key, default)

            for cb_func in rel.on_get:
                cb_func(self, value)

            return value

        def fset(self, value):
            """
            Set the related BizObject or list, enuring that a list can't be
            assigned to a Relationship with many == False and vice versa.
            """
            rel = self.relationships[key]

            if rel.readonly:
                raise RelationshipError(f'{rel} is read-only')

            if value is None and rel.many:
                value = rel.target.BizList([], rel, self)
            elif is_sequence(value):
                value = rel.target.BizList(value, rel, self)

            is_scalar = not isinstance(value, BizList)
            expect_scalar = not rel.many

            if (not expect_scalar) and isinstance(value, dict):
                # assume that the value is a map from id to bizobj, so
                # convert the dict value set into a list to use as the
                # value set for the Relationship.
                value = list(value.values())

            if is_scalar and not expect_scalar:
                raise ValueError(
                    'relationship "{}" must be a sequence because '
                    'relationship.many is True'.format(key)
                )
            elif (not is_scalar) and expect_scalar:
                raise ValueError(
                    'relationship "{}" cannot be a BizObject because '
                    'relationship.many is False'.format(key)
                )
            self._related[key] = value

            if (not rel.many) and rel.conditions:
                RelationshipProperty.set_foreign_keys(self, value, rel)

            for cb_func in rel.on_set:
                cb_func(self, value)

        def fdel(self):
            """
            Remove the related BizObject or list. The field will appeear in
            dump() results. You must assign None if you want to None to appear.
            """
            if rel.readonly:
                raise RelationshipError(f'{rel} is read-only')

            value = self._related[key]
            del self._related[key]
            for cb_func in rel.on_del:
                cb_func(self, value)

        return cls(relationship, fget=fget, fset=fset, fdel=fdel)

    @staticmethod
    def set_foreign_keys(bizobj, related_bizobj, rel):
        """
        When setting a relationship, we might be able to set any fields declared
        on the host bizobj based on the contents of the Relationship's query
        predicates. For example, a node might have a parent_id field, which we
        would want to set when doing somehing like child.parent = parent (we
        would want child.parent_id = parent._id to be performed automatically).
        """
        pred = rel.conditions[0](MockBizObject())
        if isinstance(pred, ConditionalPredicate):
            if pred.op == OP_CODE.EQ:
                attr_name = pred.value
                related_attr_name = pred.field.name
                related_value = getattr(related_bizobj, related_attr_name, None)
                setattr(bizobj, attr_name, related_value)
