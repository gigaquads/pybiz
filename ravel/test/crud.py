import re
import random

from typing import Type

import pytest

from appyratus.utils.dict_utils import DictUtils

from ravel.test.domains.things import Thing as BaseThing
from ravel.constants import REV, ID
from ravel import Application, Store, Resource

__all__ = [
    'ResourceCrudTestSuite',
    'Thing',
    'random_things',
    'app',
]


@pytest.fixture(scope='function')
def app():
    return Application().bootstrap()


@pytest.fixture(scope='function')
def Thing(app):
    class Thing(BaseThing):
        pass

    app.register_resource(Thing)
    return Thing


@pytest.fixture(scope='function')
def random_things(Thing):
    return Thing.Batch.generate(count=64).merge(anything=1)


class ResourceCrudTestSuite:

    @classmethod
    def build_store(cls, app: Application) -> Store:
        """
        Return a bootstrapped Store object.
        """
        raise NotImplementedError('override in subclass')

    @classmethod
    def bind_store(cls, resource_type, store) -> Store:
        """
        Bind the Store with the Resource
        """
        store.bind(resource_type)

    @classmethod
    def bind(cls, resource_type: Type[Resource]):
        cls.store = cls.build_store(resource_type.ravel.app)
        cls.bind_store(resource_type, cls.store)
        resource_type.ravel.local.store = cls.store

    def test_create(self, Thing, random_things):
        self.bind(Thing)

        for thing in random_things:
            assert thing.dirty

            old_state = thing.internal.state.copy()
            thing.create()
            new_state = thing.internal.state.copy()

            # created objects should have no dirty fields
            assert not thing.dirty

            # comparing state before and after create()
            for k, v_old in old_state.items():
                v_new = new_state[k]

                if k == REV:
                    # rev is always generated by the Store
                    assert v_new is not None

                    # make sure rev string has correct structure
                    assert re.match(f'[a-z0-9]+-[a-z0-9]+', v_new)
                else:
                    # make sure field value hasn't changed following create
                    assert v_old == v_new

    def test_create_with_no_ids(self, Thing, random_things):
        self.bind(Thing)

        # make sure the store generates an ID if
        # none was passed into the create method
        for thing in random_things:
            thing._id = None
            assert thing._id is None
            thing.create()
            assert thing._id is not None

    def test_create_with_null_not_nullable_fields(self, Thing, random_things):
        Thing.name.resolver.nullable = False
        Thing.name.resolver.field.nullable = False

        random_things.name = None
        for thing in random_things:
            with pytest.raises(Exception):
                thing.create()

    def test_update(self, Thing, random_things):
        self.bind(Thing)

        for idx, thing in enumerate(random_things):
            thing.create()
            assert not thing.dirty

            if idx % 2:
                # set ever other thing's rev to make sure
                # that, following update, this erroneous value
                # is discoarded and the new real rev is set.
                thing._rev = 'foobar'

            # calling mark with no arguments makes *all* fields
            # in its state dict dirty
            thing.mark()
            assert thing.dirty

            # call update and ensure that nothing is dirty
            thing.update()
            assert not thing.dirty
            if idx % 2:
                assert thing._rev != 'foobar'

    def test_get(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)
        all_field_names = list(Thing.Schema.fields.keys())

        for thing in random_things:
            field_names = {
                random.choice(all_field_names) for i in
                range(len(all_field_names))
            }

            thing_copy = Thing.get(thing._id, field_names)

            assert thing_copy is not None
            assert not thing_copy.dirty
            assert ID in thing_copy.internal.state
            assert REV in thing_copy.internal.state
            assert (
                set(thing_copy.internal.state.keys())
                    == (field_names | {REV, ID})
            )

    def test_get_without_fields_kwarg(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        for thing in random_things:
            thing_copy = Thing.get(thing._id)
            assert thing_copy is not None
            assert not thing_copy.dirty
            assert ID in thing_copy.internal.state
            assert REV in thing_copy.internal.state

    def test_get_many(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        all_field_names = list(Thing.Schema.fields.keys())
        thing_ids = [thing._id for thing in random_things]

        for _ in range(10):
            field_names = {
                random.choice(all_field_names) for i in
                range(len(all_field_names))
            }

            thing_copies = Thing.get_many(thing_ids, field_names)

            assert thing_copies
            assert not any(x.dirty for x in thing_copies)
            assert len(set(thing_copies._id)) == len(random_things)

            for thing_copy in thing_copies:
                assert thing_copy._rev is not None
                assert (
                    set(thing_copy.internal.state.keys())
                        == (field_names | {REV, ID})
                )

    def test_get_many_without_fields_kwarg(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        thing_copies = Thing.get_many(random_things._id)

        assert thing_copies
        assert not any(x.dirty for x in thing_copies)
        assert all(x._id for x in thing_copies)
        assert all(x._rev for x in thing_copies)

    def test_delete(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        for thing in random_things:
            thing_copy = Thing.get(thing._id, {ID})
            assert thing_copy is not None

            thing.delete()

            thing_copy = Thing.get(thing._id, {ID})

            assert thing_copy is None
            assert Thing.Schema.fields.keys() == thing.dirty.keys()

    def test_delete_many(self, Thing, random_things):
        self.bind(Thing)

        for _ in range(10):
            Thing.create_many(random_things)
            thing_ids = random_things._id

            Thing.delete_many(random_things)

            thing_copies = Thing.get_many(thing_ids, {ID})

            assert not any(x._id for x in thing_copies)
            assert not any(x._rev for x in thing_copies)
            assert all(x.dirty for x in thing_copies)

    def test_exists(self, Thing, random_things):
        self.bind(Thing)

        for thing in random_things:
            assert not Thing.exists(thing)

        Thing.create_many(random_things)

        for thing in random_things:
            assert Thing.exists(thing)

    def test_exists_many(self, Thing, random_things):
        self.bind(Thing)

        for thing in random_things:
            assert not Thing.exists(thing)
            if random.randint(0, 1):
                thing.create()

        exists = Thing.exists_many(random_things._id)

        for thing in random_things:
            if thing.dirty:
                assert exists[thing._id] is False
            else:
                assert exists[thing._id] is True

    def test_create_many(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)
        thing_copies = Thing.get_many(random_things._id)

        assert not any(x.dirty for x in thing_copies)
        assert all(x._id for x in thing_copies)
        assert all(x._rev for x in thing_copies)

    def test_update_many(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        # collect revs prior to updating all
        old_revs = set(random_things._rev)

        # make each thing dirty
        for thing in random_things:
            thing.merge(Thing.generate(), anything=1)

        # call func under test, fetch updated resources
        Thing.update_many(random_things)
        thing_copies = Thing.get_many(random_things._id)

        # everything should have an id and rev and be clean
        assert not any(x.dirty for x in thing_copies)
        assert all(x._id for x in thing_copies)
        assert all(x._rev for x in thing_copies)

        # all new revs should have been generated
        assert not (old_revs & set(thing_copies._rev))

    def test_save(self, Thing, random_things):
        self.bind(Thing)
        for thing in random_things:
            if random.randint(0, 1):
                thing.save()
            else:
                thing.create()
                thing.merge(Thing.generate(), anything=1).save()

            assert not thing.dirty
            assert thing._id is not None
            assert thing._rev is not None

    def test_save_many(self, Thing, random_things):
        self.bind(Thing)

        id_2_old_revs = {}

        # save a random subset of things
        for thing in random_things:
            if random.randint(0, 1):
                thing.create()
                id_2_old_revs[thing._id] = thing._rev

        # now call save, expecting some update calls
        # and some create calls internally.
        Thing.save_many(random_things)
        thing_copies = Thing.get_many(random_things._id)

        assert not any(x.dirty for x in thing_copies)
        assert all(x._id for x in thing_copies)
        assert all(x._rev for x in thing_copies)

        # make sure new revs are generated for
        # the merely updated resources, for both
        # in-memory copies and newly fetch ones.
        for thing in random_things:
            if thing._id in id_2_old_revs:
                assert id_2_old_revs[thing._id] != thing._rev
        for thing in thing_copies:
            if thing._id in id_2_old_revs:
                assert id_2_old_revs[thing._id] != thing._rev

    def test_query_no_params(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)
        query = Thing.select(Thing._id)
        results = query.execute()

        assert len(results) == len(random_things)
        assert not any(x.dirty for x in results)
        assert set(results._id) == set(random_things._id)
        assert set(results._rev) == set(random_things._rev)

        for thing in results:
            assert thing.internal.state.keys() == {
                ID, REV
            }

    def test_query_with_where_clause(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)
        query = Thing.select(Thing._id).where(Thing._id == random_things[0]._id)
        results = query.execute()

        assert len(results) == 1
        assert not any(x.dirty for x in results)

        queried_thing = random_things[0]
        result_thing = results[0]

        assert result_thing._id == queried_thing._id
        assert result_thing._rev == queried_thing._rev

    def test_query_with_limit_and_offset(self, Thing, random_things):
        self.bind(Thing)

        Thing.create_many(random_things)

        visited_ids = set()
        for offset in range(len(random_things)):
            # query each resource one by one
            query = Thing.select(Thing._id).limit(1).offset(offset)
            results = query.execute()

            assert len(results) == 1

            result = results[0]

            # make sure we haven't already seen its id
            assert result._id not in visited_ids

            visited_ids.add(result._id)

    @pytest.mark.parametrize('desc', [True, False, None])
    def test_query_with_order_by(self, Thing, random_things, desc):
        self.bind(Thing)

        Thing.create_many(random_things)

        if desc is True:
            # ensure results are ordered descending order or rev string
            query = Thing.select(Thing._id).order_by(Thing._rev.desc)
            results = query.execute()

            assert len(results) == len(random_things)
            for thing_1, thing_2 in zip(results, results[1:]):
                assert thing_1._rev >= thing_2._rev
        else:
            # ensure results are ordered ascending order or rev string
            if desc is False:
                query = Thing.select(Thing._id).order_by(Thing._rev.asc)
            else:
                query = Thing.select(Thing._id).order_by(Thing._rev)
            results = query.execute()

            assert len(results) == len(random_things)
            for thing_1, thing_2 in zip(results, results[1:]):
                assert thing_1._rev <= thing_2._rev
