import pytest
import ravel


@pytest.fixture(scope='function')
def app():
    return ravel.Application().bootstrap()


@pytest.fixture(scope='function')
def Node(app):
    class Node(ravel.Resource):
        name = ravel.String(required=True)
        parent_id = ravel.Id(required=True)

        @ravel.relationship(join=lambda: (Node.parent_id, Node._id))
        def parent(self):
            pass

        @ravel.relationship(join=lambda: (Node._id, Node.parent_id), many=True)
        def children(self):
            pass

    app.bind(Node)
    return Node


@pytest.fixture(scope='function')
def parent(Node):
    return Node(name='parent').save()


@pytest.fixture(scope='function')
def children(Node, parent):
    return Node.Batch(
        Node(name=f'child {c}', parent_id=parent._id)
        for c in 'ABC'
    ).save()


def test_children_resolve_parent(parent, children):
    for node in children.parent:
        assert node is not None
        assert node._id == parent._id


def test_parent_resolves_children(parent, children):
    child_ids = set(children._id)
    for node in parent.children:
        assert node is not None
        import ipdb; ipdb.set_trace()
        assert node._id in child_ids
