import ujson

from typing import Text

from appyratus.validation.fields import Str
from appyratus.json import JsonEncoder


def remote_dao_endpoint_factory(rpc: 'GrpcFunctionRegistry')
    """
    Build and return the endpoint function used by gRPC clients to execute
    method on Dao objects remotely. This factory adds the dynamically defined
    function to the rpc function registry argument.
    """
    @rpc(
        request={
            'dao_type': Str(),
            'method_name': Str(),
            'args_json': Str(),
        },
        response={
            'data': Str(),
        }
    )
    def apply_dao_method(dao_type: Text, method_name: Text, args_json: Text):
        """
        Calls a Dao interface method on behalf of a remote client.
        """
        args = ujson.loads(args_json)
        # get the Dao class
        dao_type = rpc.dao_types.get(dao_type, None)
        if dao_type is not None:
            # get an instance of said class
            dao = dao_type()
            # get the Dao method to call
            func = getattr(dao, method_name, None)
            if func is not None:
                # call the Dao method with the args dict
                data = func(**args)
                encoder = JsonEncoder()
                return {'data': encoder.encode(data)}
            else:
                raise Exception('unrecognized DAO method name')
        else:
            raise Exception('unrecognized DAO type')

    return apply_dao_method

