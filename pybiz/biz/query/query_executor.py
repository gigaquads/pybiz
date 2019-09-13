import bisect

from functools import reduce
from typing import List, Dict, Set, Text, Type, Tuple

from pybiz.util.misc_functions import is_bizobj, is_bizlist, is_sequence
from pybiz.predicate import Predicate

from ..biz_list import BizList


class QueryExecutor(object):
    def execute(
        self,
        query: 'Query',
        backfiller: 'QueryBackfiller' = None,
        constraints: Dict[Text, 'Constraint'] = None,
        first: bool = False,
    ):
        """
        Args:
        - `query` - The Query we are executing recursively.
        - `backfiller` - The QueryBackfiller being used to backfill, if defined.
        - `constraints` - The Field value constraints used by the backfiller
        - `first` - Return the first BizObject from the fetched/backfilled
            result "target" BizObjects
        """
        target_biz_class = query.biz_class
        target_dao = target_biz_class.get_dao()

        # if multiple individual "where" predicates exist, join them via
        # conjunction in a single "root" predicate to use as the argument passed
        # int othe Dao.qeuery method.
        if query.params.where:
            root_predicate = Predicate.reduce_and(*query.params.where)
        else:
            root_predicate = (target_biz_class._id != None)

        # Fetch the raw dict records from the Dao. Otherwise,
        records = target_dao.query(
            predicate=root_predicate, fields=query.params.fields,
            order_by=query.params.order_by, limit=query.params.limit,
            offset=query.params.offset,
        )

        # `targets` refers to the BizObjects loaded through the Query.
        targets = target_biz_class.BizList(
            target_biz_class(x) for x in records
        ).clean()

        # Note that any FieldPropertyQuery executed on the field will result
        # in the queried BizObject being returned "dirty" to the caller.
        for field_name, fprop_query in query.params.fields.items():
            if fprop_query is not None:
                for biz_obj in targets:
                    biz_obj[field_name] = fprop_query.execute(biz_obj)

        # if we're backfilling, ensure that we get at least 1 BizObject back in
        # case the Dao query returned a number of records smaller than the
        # requested limit or none at all,
        if backfiller and (len(targets) < (query.params.limit or 1)):
            targets = backfiller.generate(
                query=query,
                count=(1 if first else None),
                constraints=constraints,
            )
        # enter indirect recursion via the Relationships defined on the fetched
        # target BizObjects.
        self._execute_recursive(query, backfiller, targets)

        return targets

    def _execute_recursive(
        self,
        query: 'Query',
        backfiller: 'QueryBackfiller',
        sources: List['BizObject'],
    ):
        """
        Args:
        - `query`: The Query object whose selected Relationships and other
            BizAttributes we are iterating over and recursively executing.
        - `backfiller`: The QueryBackfiller being used to backfill queried
            BizObjects throughout this recursive procedure.
        - `sources`: The BizObjects whose Relationships we are recursively
            executing here.
        """
        # class whose relationships we are executing
        source_biz_class = query.biz_class

        # Sort attribute names by their BizAttribute priority.
        ordered_biz_attrs = self._sort_biz_attrs(query)

        # Execute each BizAttribute on each BizObject individually. a nice to
        # have would be a bulk-execution interface built built into the
        # BizAttribute base class
        for biz_attr in ordered_biz_attrs:
            sub_query = query.params.attributes[biz_attr.name]

            # Process Relationships. Other BizAttribute values are generated by
            # the QueryBackfiller via indirect recursion through the
            # Relationship.execute method.
            if biz_attr.category == 'relationship':
                rel = biz_attr
                params = self._prepare_relationship_query_params(sub_query)

                # `next_sources_set` is used to collect all distinct BizObjects
                # loaded via this Relationship on all source BizObjects. This is
                # eventually transformed int oa a BizList and passed into a
                # recursive call to this method as the next "sources" argument.
                next_sources_set = set()

                # Execute the relationship's underlying query before
                # backfilling if necessary.
                target_biz_things = rel.execute(sources, **params)

                # Zip up each source BizObject with corresponding targets
                for source, target_biz_thing in zip(sources, target_biz_things):
                    if backfiller is not None:
                        target_biz_thing = self._backfill_relationship(
                            source, target_biz_thing, rel, backfiller, params
                        )
                    # add BizObjects(s) to accumulator set
                    if rel.many:
                        next_sources_set.update(target_biz_thing)
                    else:
                        next_sources_set.add(target_biz_thing)

                    setattr(source, rel.name, target_biz_thing)

                # recursively execute subqueries for next_sources BizObjects
                next_sources_biz_list = rel.target_biz_class.BizList(
                    next_sources_set
                )
                self._execute_recursive(
                    query=sub_query,
                    backfiller=backfiller,
                    sources=next_sources_biz_list,
                )

        return sources

    def _sort_biz_attrs(self, query):
        ordered_biz_attrs = []
        for biz_attr_name, sub_query in query.params.attributes.items():
            biz_attr = query.biz_class.attributes.by_name(biz_attr_name)
            bisect.insort(ordered_biz_attrs, biz_attr)
        return ordered_biz_attrs

    def _prepare_relationship_query_params(self, sub_query):
        """
        Translate the Query params data into the kwargs expected by
        Relationip.execute/generate.
        """
        return {
            'select': set(sub_query.params.fields.keys()),
            'where': sub_query.params.where,
            'order_by': sub_query.params.order_by,
            'limit': sub_query.params.limit,
            'offset': sub_query.params.offset,
        }

    def _backfill_relationship(
        self, source, target_biz_thing, rel, backfiller, params
    ):
        """
        Ensure that each target BizList is not empty and, if a limit is
        specified, has a length equal to said limit.
        """
        limit = params['limit']
        if limit is None:
            target_biz_thing = rel.generate(
                source, backfiller=backfiller, **params
            )
        elif limit and (len(target_biz_thing) < limit):
            assert is_bizlist(target_biz_thing)
            params = params.copy()
            params['limit'] = limit - len(target_biz_thing)
            target_biz_thing.extend(
                rel.generate(source, backfiller=backfiller, **params)
            )
        return target_biz_thing
