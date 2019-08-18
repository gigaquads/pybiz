import pytest
import pybiz

from appyratus.test import mark


class TestApplicationBasics(object):
    """
    TODO:
    """

    @mark.integration
    def test_positional_arg_is_loaded_from_id(cls, startrek, captain_picard):
        captain_picard.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_officer,
            args=(captain_picard._id, )
        )
        assert isinstance(args[0], startrek.biz.Officer)
        assert args[0]._id == captain_picard._id

    @mark.integration
    def test_positional_arg_is_loaded_from_dict(cls, startrek, captain_picard):
        captain_picard.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_officer,
            args=(captain_picard.dump(), )
        )
        assert isinstance(args[0], startrek.biz.Officer)
        assert args[0]._id == captain_picard._id

    @mark.integration
    def test_positional_arg_is_loaded_from_bizobj(cls, startrek, captain_picard):
        captain_picard.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_officer,
            args=(captain_picard, )
        )
        assert isinstance(args[0], startrek.biz.Officer)
        assert args[0]._id == captain_picard._id

    @mark.integration
    def test_kw_arg_is_loaded_from_id(cls, startrek, the_enterprise):
        the_enterprise.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_ship,
            kwargs={'ship': the_enterprise._id}
        )
        assert isinstance(kwargs['ship'], startrek.biz.Ship)
        assert kwargs['ship']._id == the_enterprise._id

    @mark.integration
    def test_kw_arg_is_loaded_from_dict(cls, startrek, the_enterprise):
        the_enterprise.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_ship,
            kwargs={'ship': the_enterprise.dump()}
        )
        assert isinstance(kwargs['ship'], startrek.biz.Ship)
        assert kwargs['ship']._id == the_enterprise._id

    @mark.integration
    def test_kw_arg_is_loaded_from_bizobj(cls, startrek, the_enterprise):
        the_enterprise.create()
        args, kwargs = startrek.argument_loader.load(
            endpoint=startrek.endpoints.get_ship,
            kwargs={'ship': the_enterprise}
        )
        assert isinstance(kwargs['ship'], startrek.biz.Ship)
        assert kwargs['ship']._id == the_enterprise._id
