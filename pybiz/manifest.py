import os
import inspect
import importlib

import yaml
import venusian

from typing import Text

from appyratus.schema import fields, Schema
from appyratus.decorators import memoized_property
from appyratus.types import DictAccessor

from pybiz.dao.base import DaoManager
from pybiz.exc import ManifestError


class ManifestSchema(Schema):
    """
    Describes the structure expected in manifest.yaml files.
    """

    class BindingSchema(Schema):
        biz = fields.String(required=True)
        dao = fields.String(required=True)

    package = fields.String(required=True)
    bindings = fields.List(BindingSchema(), default=lambda: [])


class Manifest(object):
    """
    This thing reads manifest.yaml files and bootstraps each layer of the
    framework, namely:

        1. Associate each listed BizObject class with the Dao class it is
           with which it is associated.

        2. Do a venusian scan on the api endpoint packages and modules, which
           has the side-effect of registering the api callables with the
           ApiRegistry via ApiRegistryDecorators.
    """

    def __init__(self, filepath=None):
        self.scanner = venusian.Scanner(
            bizobj_classes={},
            schema_classes={},
            dao_classes={},
        )
        self.filepath = self._resolve_filepath(filepath)
        self.data, errors = self._load_manifest_file()
        if errors:
            raise ManifestError(str(errors))

    def process(self):
        """
        Interpret the manifest file data, bootstrapping the layers of the
        framework.
        """
        self._scan()
        self._bind()
        return self

    @property
    def package(self):
        return self.data['package']

    @memoized_property
    def biz_types(self) -> DictAccessor:
        return DictAccessor(self.scanner.bizobj_classes)

    @memoized_property
    def dao_types(self) -> DictAccessor:
        return DictAccessor(self.scanner.dao_classes)

    @memoized_property
    def schemas(self) -> DictAccessor:
        return DictAccessor(self.scanner.schema_classes)

    @staticmethod
    def _resolve_filepath(filepath: Text):
        """
        Return the filepath to the manifest.yaml file. Search the Check for env
        var with the structure: PYBIZ_MANIFEST if the filepath argument
        is None.
        """
        if filepath is None:
            env_var_name = 'PYBIZ_MANIFEST'
            filepath = os.environ.get(env_var_name)

        if filepath is None:
            raise ManifestError('could not find pybiz manifest file')

        return filepath

    def _load_manifest_file(self):
        with open(self.filepath) as manifest_file:
            schema = ManifestSchema()
            manifest_dict = yaml.load(manifest_file)
            return schema.process(manifest_dict)

    def _scan(self):
        """
        Use venusian simply to scan the endpoint packages/modules, causing the
        endpoint callables to register themselves with the Api instance.
        """

        def onerror(name):
            import sys, re
            if issubclass(sys.exc_info()[0], ImportError):
                # XXX add logging otherwise things like import errors do not surface
                if re.match(r'^\w+\.grpc', name):
                    return

        pkg = importlib.import_module(self.data['package'])
        self.scanner.scan(pkg, onerror=onerror)

    def _bind(self):
        """
        Associate each BizObject class with a corresponding Dao class. Also bind
        Schema classes to their respective BizObject classes.
        """
        manager = DaoManager.get_instance()
        for binding in (self.data.get('bindings') or []):
            biz_class = self.scanner.bizobj_classes[binding['biz']]
            dao_class = self.scanner.dao_classes[binding['dao']]
            manager.register(biz_class, dao_class)
