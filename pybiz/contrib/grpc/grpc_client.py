import codecs
import pickle

import grpc

from typing import Text

from appyratus.utils import StringUtils

from pybiz.schema import fields, Schema, Field


class GrpcClient(object):
    def __init__(self, app: 'GrpcApplication'):
        assert app.is_bootstrapped

        self._address = app.grpc.options.client_address
        self._app = app

        print('Connecting to {}'.format(self._address))

        if app.grpc.options.secure_channel:
            self._channel = grpc.secure_channel(
                self._address, grpc.ssl_channel_credentials()
            )
        else:
            self._channel = grpc.insecure_channel(self._address)

        GrpcApplicationStub = app.grpc.pb2_grpc.GrpcApplicationStub

        self._grpc_stub = GrpcApplicationStub(self._channel)
        self._funcs = {
            k: self._build_func(p)
            for k, p in app.endpoints.items()
        }

    def __getattr__(self, func_name: Text):
        return self._funcs[func_name]

    def _build_func(self, endpoint):
        key = StringUtils.camel(endpoint.name)
        request_class = getattr(self._app.grpc.pb2, f'{key}Request')
        send_request = getattr(self._grpc_stub, endpoint.name)

        def func(**kwargs):
            # prepare and send the request
            request = request_class(**kwargs)
            response = send_request(request)
            # translate the native proto response message to a plain dict
            data = self._extract_fields(response, endpoint.response_schema)
            return data

        return func

    def _extract_fields(self, message, schema):
        result = {}
        for field_name, field in schema.fields.items():
            value = getattr(message, field_name, None)
            if isinstance(field, fields.Dict):
                decoded_value = codecs.decode(value, 'base64')
                result[field_name] = pickle.loads(decoded_value)
            elif isinstance(field, fields.Nested):
                result[field_name] = self._extract_fields(value, field.schema)
            elif isinstance(field, fields.List):
                if isinstance(field.nested, Schema):
                    result[field_name] = [
                        self._extract_fields(v, field.nested) for v in value
                    ]
                elif isinstance(field.nested, fields.Dict):
                    result[field_name] = [
                        pickle.loads(codecs.decode(v, 'base64')) for v in value
                    ]
                else:
                    result[field_name] = list(value)
            elif isinstance(field, fields.Set):
                if isinstance(field.nested, Schema):
                    result[field_name] = {
                        self._extract_fields(v, field.nested)
                        for v in value
                    }
                elif isinstance(field.nested, fields.Dict):
                    result[field_name] = {
                        pickle.loads(codecs.decode(v, 'base64'))
                        for v in value
                    }
                else:
                    result[field_name] = set(value)
            elif isinstance(field, Schema):
                result[field_name] = self._extract_fields(value, field)
            else:
                result[field_name] = value
        return result
