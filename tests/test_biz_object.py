import os

os.environ['PYBIZ_CONSOLE_LOG_LEVEL'] = 'WARN'

from mock import MagicMock

import pytest

import ravel

from ravel import Application
from ravel.constants import ID_FIELD_NAME
from ravel.biz.resource import Resource
from ravel.biz.query.query import Query
from ravel.biz.relationship import (
    Relationship,
    RelationshipBatch,
)
from ravel import (
    Resolver,
    ResolverProperty,
    resolver,
    relationship,
)



@pytest.fixture(scope='function')
def app():
    return Application().bootstrap()


@pytest.fixture(scope='function')
def Person(app):
    class Person(Resource):
        name = ravel.String()

    app.bind(Person)
    return Person


@pytest.fixture(scope='function')
def Dog(app, Person):
    class Dog(Resource):
        mother_id = ravel.Id()
        color = ravel.String()
        name = ravel.String()
        age = ravel.Int()

        @resolver
        def mother(self, resolver, request):
            return Dog(color='brown', age=12)

        @mother.on_get
        def mother(self, resolver, mother):
            print(f'Getting mother of {self}')

        """
        @relationship(join=lambda: Dog.owner_id, Person._id))
        def owner(self, relationship, request):
            return Person(name='Todd')

        @relationship()
        @relationship(join=lambda: Dog.owner_id, Person._id))
        def friends(self, relationship, request):
            return [Person(name='Todd')]
        """

    app.bind(Dog)
    return Dog


@pytest.fixture(scope='function')
def DogMan(app, Dog):
    class DogMan(Dog):
        name = ravel.String()

    DogMan.bootstrap(app)
    return DogMan


@pytest.fixture(scope='function')
def lassie(Dog):
    return Dog(color='brownish', age=8).save()


def test_basic_schema_creation(Dog):
    assert Dog.Schema is not None
    assert issubclass(Dog.Schema, ravel.Schema)
    assert isinstance(Dog.ravel.schema, Dog.Schema)

    assert isinstance(Dog.Schema.fields['color'], ravel.String)
    assert isinstance(Dog.Schema.fields['age'], ravel.Int)


def test_schema_creation_with_inheritance(Dog, DogMan):
    assert DogMan.Schema.fields['color'] is not Dog.Schema.fields['color']
    assert DogMan.Schema.fields['age'] is not Dog.Schema.fields['age']

    assert isinstance(DogMan.Schema.fields['color'], ravel.String)
    assert isinstance(DogMan.Schema.fields['age'], ravel.Int)
    assert isinstance(DogMan.Schema.fields['name'], ravel.String)


def test_id_field_value_generated_in_ctor(Dog):
    dog = Dog()
    assert dog._id is not None

    dog = Dog(_id='1' * 32)
    assert dog._id == '1' * 32


@pytest.mark.parametrize('dirty_field_names', [
    set(),
    {'_id'},
    {'name'},
    {'color'},
    {'name', 'color'},
])
def test_correct_fields_are_marked_dirty(Dog, dirty_field_names):
    dog = Dog(Dog.ravel.schema.generate()).clean()
    dog.clean()
    assert not dog.dirty
    dog.mark(dirty_field_names)
    assert set(dog.dirty.keys()) == dirty_field_names

def test_id_fields_are_replaced(Dog):
    replacement_field = Dog.replace_id_field(ravel.Id())
    assert not isinstance(Dog.Schema.fields[ID_FIELD_NAME], ravel.Id)
    assert isinstance(Dog.Schema.fields[ID_FIELD_NAME], type(replacement_field))


def test_field_property_gets_value(Dog):
    dog = Dog()
    dog.internal.state['color'] = 'red'
    assert dog.color == 'red'


def test_field_property_sets_value(Dog):
    dog = Dog()

    assert dog.internal.state.get('color') is None
    assert 'color' not in dog.internal.state

    dog.color = 'red'
    assert 'color' in dog.internal.state
    assert dog.internal.state.get('color') == 'red'


def test_field_property_deletes_value(Dog):
    dog = Dog()

    dog.color = 'red'
    assert 'color' in dog.internal.state
    assert dog.internal.state['color'] == 'red'

    del dog.color
    assert dog.internal.state.get('color') is None
    assert 'color' not in dog.internal.state


def test_resolver_is_registerd_via_decorator(Dog):
    assert 'mother' in Dog.ravel.resolvers


def test_resolver_decorator_is_replaced_with_property(Dog):
    assert isinstance(Dog.mother, ResolverProperty)


def test_resolver_executes_correct_method(Dog):
    mother = Dog.ravel.resolvers['mother'].execute(MagicMock())
    assert mother.color == 'brown'
    assert mother.age == 12


def test_resolver_executes_on_get_when_got(Dog):
    Dog.ravel.resolvers['mother'].on_get = on_get = MagicMock()
    dog = Dog()
    mother = dog.mother
    on_get.assert_called_once()


def test_create(Dog):
    dog = Dog(color='red', age=12).create()
    dog_data = dog.store.fetch(_id=dog._id)
    assert dog_data == dog.internal.state


def test_update(Dog, lassie):
    dog = Dog.get(lassie._id)
    assert dog.color == 'brownish'

    lassie.update(color='red')

    dog = Dog.get(lassie._id)
    assert dog.color == 'red'


def test_resolvers_correctly_assembled(Dog):
    assert Dog.ravel.resolvers['mother'] is Dog.mother.resolver
    assert Dog.ravel.resolvers.untagged['mother'] is Dog.mother.resolver
