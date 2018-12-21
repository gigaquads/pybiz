import copy

from typing import Dict
from collections import defaultdict

from appyratus.utils import StringUtils, DictUtils

from pybiz.util import is_bizobj

# TODO: Rewrite dump procedures to only dump relationship links if specified in
# fields

class DumpMethod(object):
    def dump(
        self,
        bizobj,
        depth: int,
        fields: Dict = None,
        parent: Dict = None,
    ):
        pass

    def dump_fields(self, bizobj, include: Dict):
        # copy field data into the record
        record = {
            'id': bizobj._id
        }
        for k, field in bizobj.schema.fields.items():
            if k == '_id':
                continue
            if (include is not None) and (k not in include):
                continue
            elif not field.meta.get('private', False):
                if k not in bizobj.data:
                    continue
                v = bizobj.data[k]
                # convert data to primitive types recognized as valid JSON
                # and other serialization formats more generally
                if isinstance(v, (dict, list)):
                    record[k] = copy.deepcopy(v)
                elif isinstance(v, (set, tuple)):
                    record[k] = list(v)
                else:
                    record[k] = v

        return record

    def insert_relationship_fields(self, bizobj, record: Dict, include: Dict):
        for k, rel in bizobj.relationships.items():
            if (include is not None) and (k not in include):
                continue
            if rel.links:
                if callable(rel.links):
                    record[k] = rel.links(bizobj)
                else:
                    record[k] = getattr(bizobj, rel.links)


class NestingDumpMethod(DumpMethod):
    def dump(
        self,
        bizobj,
        depth: int,
        fields: Dict = None,
        parent: Dict = None,
    ):
        if parent is None:
            include = DictUtils.unflatten_keys(fields) if fields else None
        elif fields is True:
            include = None
        else:
            include = fields

        record = self.dump_fields(bizobj, include)

        if not depth:
            self.insert_relationship_fields(bizobj, record, include)

        # recursively dump nested bizobjs
        for k, rel in bizobj.relationships.items():
            if (include is not None) and (k not in include):
                continue

            child_fields = include.get(k) if include else None
            if isinstance(child_fields, dict):
                next_depth = 1
            elif depth > 0:
                next_depth = depth - 1
            else:
                continue

            if k not in bizobj.related:
                if child_fields and k in child_fields:
                    raise Exception('expected {} to be loaded'.format(k))
                continue

            v = bizobj.related[k]

            # dump the bizobj or list of bizobjs
            if is_bizobj(v):
                record[k] = self.dump(
                    v, next_depth, fields=child_fields, parent=record,
                )
            elif rel.many:
                record[k] = [
                    self.dump(
                        x, next_depth, fields=child_fields, parent=record,
                    ) for x in v
                ]
            else:
                record[k] = None

        return record


class SideLoadingDumpMethod(DumpMethod):
    def dump(
        self,
        bizobj,
        depth: int,
        fields: Dict = None,
        result: Dict = None
    ):
        if depth < 1:
            # base case
            result['links'] = dict(result['links'])
            return result

        if result is None:
            # if here, this is the initial call, not a recursive one
            include = DictUtils.unflatten_keys(fields) if fields else None
            record = self.dump_fields(bizobj, include)
            self.insert_relationship_fields(bizobj, record, include)
            result = {
                'target': record,
                'links': defaultdict(dict),
            }
        elif fields is True:
            include = None
        else:
            include = fields

        # recursively process child relationships
        for k, rel in bizobj.relationships.items():
            if (include is not None) and (k not in include):
                continue

            # get the related bizobj or list thereof
            obj = bizobj.related.get(k)

            # get the fields to query for the related bizobj(s)
            related_fields = include.get(k)
            if related_fields is True:
                related_fields = None

            # lazy load the related bizobj(s)
            if (obj is None) and (rel.query is not None):
                obj = rel.query(bizobj, fields=related_fields)

            # put pairs of (bizobj, fields) into array for recursion
            if rel.many:
                related_items = zip(obj, [related_fields] * len(obj))
            else:
                related_items = [(obj, related_fields)]

            # recurse on child bizobjs
            for related_bizobj, related_fields in related_items:
                # "kind" is the name of the public resource type that appears in
                # the "links" result dict
                kind = StringUtils.snake(related_bizobj.__class__.__name__)
                related_id = related_bizobj._id

                # only bother adding to the links dict if not already done so by
                # another bizobj higher in the tree.
                if related_id not in result['links'][kind]:
                    related_record = self.dump_fields(related_bizobj, related_fields)
                    self.insert_relationship_fields(
                        related_bizobj, related_record, related_fields
                    )
                    result['links'][kind][related_id] = related_record
                    self.dump(
                        related_bizobj,
                        depth-1,
                        fields=related_fields,
                        result=result
                    )

        return result


