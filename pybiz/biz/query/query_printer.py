from functools import reduce
from typing import Text


class QueryPrinter(object):
    def print_query(self, query: 'AbstractQuery') -> None:
        """
        Just pretty print the query.
        """
        print(self.format_query(query))

    def format_biz_attr_query(self, query, indent):
        lines = []
        for k, v in query.params.items():
            lines.append(f'{k.upper()} {v}')

        return '\n'.join(f'{" " * indent}{line}' for line in lines)

    def format_query(self, query: 'AbstractQuery', indent=0) -> Text:
        """
        Return a pretty printed string of the query in Pybiz query langauge.
        """
        from pybiz.biz import Query

        biz_class_name = query.biz_class.__name__

        # we collect all substrings of the final format string in three
        # different lists below. Formatting differs slightly for substrings
        # generated by recursive calls to this method, and this is why collect
        # them separarely here.
        pre_sub_query_substrs = []
        post_sub_query_substrs = []
        sub_query_substrs = []

        # field_names is a lexicographically sorted list of all
        # non-Relationship selectble attribute names on the target BizObject
        # class.
        field_names = []
        field_names += list(query.params.fields.keys())
        field_names.sort()

        pre_sub_query_substrs.append(f'FROM {biz_class_name} SELECT')
        for k in field_names:
            field = query.biz_class.schema.fields[k]
            pre_sub_query_substrs.append(
                f' - {k}: {field.__class__.__name__}'
            )

        # recursively render sub_queries corresponding to selected Relationships
        for name, sub_query in sorted(query.params.attributes.items()):
            if isinstance(sub_query, Query):
                type_name = sub_query.biz_class.__name__
                rel = query.biz_class.relationships.get(name)
                if rel and rel.many:
                    type_name = f'[{type_name}]'
                sub_query_substr = self.format_query(sub_query, indent=indent+5)
                sub_query_substrs.append(
                    f'{" " * indent} - {name}: {type_name} = ('
                )
                sub_query_substrs.append(sub_query_substr)
                sub_query_substrs.append(f'{" " * indent}   )')
            elif isinstance(sub_query, BizAttributeQuery):
                type_name = sub_query.biz_attr.biz_class.__name__
                sub_query_substr = self.format_biz_attr_query(
                    sub_query, indent=indent+5
                )
                sub_query_substrs.append(
                    f'{" " * indent} - {name}: {type_name} = ('
                )
                sub_query_substrs.append(sub_query_substr)
                sub_query_substrs.append(f'{" " * indent}   )')

        # render "where"-expression Predicates
        predicates = query.params.where
        if predicates:
            predicate = reduce(
                lambda x, y: x & y, query.params.where
            )
            post_sub_query_substrs.append(f'WHERE {predicate}')

        # render order by
        order_by = query.params.order_by
        if order_by:
            post_sub_query_substrs.append(
                'ORDER_BY (' + ', '.join(
                f'{x.key} {"DESC" if x.desc else "ASC"}'
                for x in order_by
            ) + ')')

        # render limit and offset
        offset = query.params.offset
        if offset is not None:
            post_sub_query_substrs.append(f'OFFSET {offset}')
        limit = query.params.limit
        if limit is not None:
            post_sub_query_substrs.append(f'LIMIT {limit}')

        # generate final format string
        fstr = '\n'.join(
            f'{" " * indent}{chunk}' for chunk in pre_sub_query_substrs
        )
        if sub_query_substrs:
            fstr += '\n' + '\n'.join(f'{chunk}' for chunk in sub_query_substrs)
        if post_sub_query_substrs:
            fstr += '\n' + '\n'.join(
                f'{" " * indent}{chunk}' for chunk in post_sub_query_substrs
            )

        return fstr
