from typing import List, Dict, Set, Text, Type, Tuple

from appyratus.utils import DictUtils

from pybiz.util import is_bizobj, is_sequence
from pybiz.constants import IS_BIZOBJ_ANNOTATION

from ..biz_list import BizList


class QuerySpecification(object):
    """
    A `QuerySpecification` is a named tuple, containing a specification of which
    fields we are selecting from a target `BizObject`, along with the fields
    nested inside related instance objects, declared in a `Relationship`.
    """

    # correspondance between tuple field names
    # to tuple positional indexes:
    name2index = {
        'fields': 0,
        'relationships': 1,
        'limit': 2,
        'offset': 3,
        'order_by': 4,
    }

    def __init__(
        self,
        fields: Set[Text] = None,
        relationships: Dict[Text, 'QuerySpecification'] = None,
        views: Set[Text] = None,
        limit: int = None,
        offset: int = None,
        order_by: Tuple = None,
        kwargs: Dict = None,
    ):
        # set epxected default values for items in the tuple.
        # always work on a copy of the input `fields` set.
        self.fields = set(fields) if fields else set()
        self.views = set(views) if views else set()
        self.relationships = {} if relationships else {}
        self.limit = min(1, limit) if limit is not None else None
        self.offset = max(0, offset) if offset is not None else None
        self.order_by = tuple(order_by) if order_by else tuple()
        self.kwargs = kwargs or {}

        self._tuplized_attrs = (
            self.fields,
            self.relationships,
            self.views,
            self.limit,
            self.offset,
            self.order_by,
            self.kwargs,
        )

    def __getitem__(self, index):
        """
        Access tuple element by name.
        """
        return self._tuplized_attrs[index]

    def __len__(self):
        return len(self._tuplized_attrs)

    def __iter__(self):
        return iter(self._tuplized_attrs)

    @classmethod
    def build(
        cls, spec, biz_type: Type['BizObject'], fields=None,
    ) -> 'QuerySpecification':
        """
        Translate input "spec" data structure into a well-formed
        QuerySpecification with appropriate starting conditions.
        """
        fields = fields or {}

        def build_recursive(biz_type: Type['BizObject'], names: Dict):
            spec = cls()
            if '*' in names:
                del names['*']
                spec.fields = set(
                    f.source for f in biz_type.schema.fields.values()
                )
            for k, v in names.items():
                field = biz_type.schema.fields.get(k)
                if field:
                    spec.fields.add(field.source)
                elif k in biz_type.relationships:
                    rel = biz_type.relationships[k]
                    if v is None:  # base case
                        spec.relationships[k] = cls()
                    elif isinstance(v, dict):
                        spec.relationships[k] = build_recursive(rel.target, v)
                elif k in biz_type.views:
                    spec.views.add(k)
            return spec

        if isinstance(spec, cls):
            if '*' in spec.fields:
                spec.fields = set(biz_type.schema.fields.keys())
            if fields:
                tmp_spec = build_recursive(
                    biz_type, DictUtils.unflatten_keys({k: None for k in fields})
                )
                spec.fields.update(tmp_spec.fields)
                spec.relationships.update(tmp_spec.relationships)
                spec.views.update(tmp_spec.views)
        elif isinstance(spec, dict):
            if fields:
                spec.update(fields)
            names = DictUtils.unflatten_keys({k: None for k in spec})
            spec = build_recursive(biz_type, names)
        elif is_sequence(spec):
            # spec is an array of field and relationship names
            # so partition the names between fields and relationships
            # in a new spec object.
            if fields:
                spec.update(fields)
            names = DictUtils.unflatten_keys({k: None for k in spec})
            spec = build_recursive(biz_type, names)
        elif not spec:
            # by default, a new spec includes all fields and relationships
            if fields:
                spec = build_recursive(
                    biz_type, DictUtils.unflatten_keys({k: None for k in fields})
                )
            else:
                spec = cls(fields={f.source for f in biz_type.schema.fields.values()})

        # ensure that _id and required fields are *always* specified
        spec.fields |= {
            f.source for f in biz_type.schema.required_fields.values()
        }
        spec.fields.add(biz_type.schema.fields['_id'].source)

        return spec


class Query(object):
    def __init__(
        self,
        biz_type: Type['BizObject'],
        predicate: 'Predicate',
        spec: 'QuerySpecification',
        fields: Set[Text] = None,
    ):
        """
        Execute a recursive query according to a given logical match predicate
        and target field/relationship spec.
        """
        self.biz_type = biz_type
        self.dao = biz_type.get_dao()
        self.spec = QuerySpecification.build(spec, biz_type, fields=fields)
        self.predicate = predicate

    def execute(self) -> List['BizObject']:
        """
        Recursively query fields from the target `BizObject` along with all
        fields nested inside related objects declared in with `Relationship`.
        """
        records = self.dao.query(
            predicate=self.predicate,
            fields=self.spec.fields,
            limit=self.spec.limit,
            offset=self.spec.offset,
            order_by=self.spec.order_by,
        )
        return self._recursively_execute_v2(
            biz_type=self.biz_type,
            bizobjs=[self.biz_type(record).clean() for record in records],
            spec=self.spec,
        )

    def _recursively_execute_v2(
        self,
        biz_type: Type['BizObject'],
        bizobjs: List['BizObject'],
        spec: 'QuerySpecification',
    ) -> 'BizList':
        for rel_name, child_spec in spec.relationships.items():
            rel = biz_type.relationships[rel_name]
            if rel.batch_loader:
                batched_data = rel.batch_loader.load(rel, bizobjs, fields=child_spec.fields)
                for bizobj, related in zip(bizobjs, batched_data):
                    rel.set_internally(bizobj, related)
                self._recursively_execute_v2(rel.target, batched_data, child_spec)
            else:
                for bizobj in bizobjs:
                    related = rel.query(
                        bizobj,
                        fields=child_spec.fields,
                        limit=child_spec.limit,
                        offset=child_spec.offset,
                        ordering=child_spec.order_by,
                        kwargs=child_spec.kwargs,
                    )
                    rel.set_internally(bizobj, related)
        for bizobj in bizobjs:
            for view_name in spec.views:
                view_data = biz_type.views[view_name].query(bizobj)
                setattr(bizobj, view_name, view_data)
        return biz_type.BizList(bizobjs)
