import importlib
import os
import re
import sys
import traceback

import yaml

from typing import Text, Dict
from collections import defaultdict

from venusian import Scanner
from appyratus.memoize import memoized_property
from appyratus.utils import DictUtils, DictObject
from appyratus.files import Yaml, Json
from appyratus.env import Environment

from pybiz.exceptions import ManifestError
from pybiz.util.misc_functions import import_object
from pybiz.util.loggers import console


class Manifest(object):
    """
    At its base, a manifest file declares the name of an installed pybiz project
    and a list of bindings, relating each BizObject class defined in the project
    with a Dao class.
    """

    def __init__(
        self,
        path: Text = None,
        data: Dict = None,
        env: Environment = None,
    ):
        from pybiz.dao import PythonDao

        self.data = data or {}
        self.path = path
        self.app = None
        self.package = None
        self.bindings = []
        self.bootstraps = {}
        self.env = env or Environment()
        self.types = DictObject({
            'dal': {
                'PythonDao': PythonDao
            },
            'biz': {},
        })
        self.scanner = Scanner(
            biz_classes=self.types.biz,
            dao_classes=self.types.dal,
            env=self.env,
        )

    def load(self):
        """
        Load and merge manifest data from all supplied sources into a single
        dict, and then create internal Manifest data structures that hold this
        data.

        Data is merged in the following order:
            1. Data supplied by the manifest YAML/JSON file
            2. Data supplied by the data __init__ kwarg

        This process prepares:
            1. self.package
            2. self.bindings
            3. self.bootstraps
        """
        base_data = self.data
        if not (self.data or self.path):
            return self

        # try to load manifest file from a YAML or JSON file
        if self.path is not None:
            console.debug(message='loading manifest file', data={'path': self.path})
            ext = os.path.splitext(self.path)[1].lstrip('.').lower()
            if ext in Yaml.extensions():
                file_data = Yaml.read(self.path)
            elif ext in Json.extensions():
                file_data = Json.read(self.path)

            # merge contents of file with data dict arg
            self.data = DictUtils.merge(file_data, self.data)

        if not self.data:
            self.data = {}

        # replace env $var names with values from env
        self._expand_environment_vars(self.env, self.data)

        console.debug(message='manifest loaded!', data={'manifest': self.data})

        self.package = self.data.get('package')

        for binding_data in (self.data.get('bindings') or []):
            biz = binding_data['biz']
            dao = binding_data.get('dao', 'PythonDao')
            params = binding_data.get('params', {})
            binding = ManifestBinding(biz=biz, dao=dao, params=params)
            self.bindings.append(binding)

        # create self.bootstraps
        self.bootstraps = {}
        for record in self.data.get('bootstraps', []):
            if '.' in record['dao']:
                dao_class_name = os.path.splitext(record['dao'])[-1][1:]
            else:
                dao_class_name = record['dao']
            self.bootstraps[dao_class_name] = ManifestBootstrap(
                dao=record['dao'], params=record.get('params', {})
            )

        return self

    def process(self, app: 'Application', namespace: Dict = None):
        """
        Discover and prepare all BizObject and Dao classes for calling the
        bootstrap and bind lifecycle methods, according to the specification
        provided by the Manifest. If `namespace` is provided, self.process will
        include this contents of this dict in its scan for BizObject and Dao
        types.
        """
        self.app = app
        self._discover_pybiz_classes(namespace)
        self._register_dao_classes()
        return self

    def bootstrap(self):
        for biz_class in self.types.biz.values():
            if not (biz_class.is_abstract or biz_class.is_bootstrapped):
                console.debug(
                    f'bootstrapping "{biz_class.__name__}" BizObject...'
                )
                biz_class.bootstrap(app=self.app)
                dao = biz_class.get_dao(bind=False)
                dao_class = dao.__class__
                if not dao_class.is_bootstrapped():
                    dao_class_name = dao_class.__name__
                    console.debug(
                        f'bootstrapping "{dao_class_name}" Dao...'
                    )
                    strap = self.bootstraps.get(dao_class_name)
                    kwargs = strap.params if strap else {}
                    dao_class.bootstrap(app=self.app, **kwargs)

        console.debug(f'finished bootstrapped Dao and BizObject classes')

        # inject the following into each endpoint target's lexical scope:
        # all other endpoints, all BizObject and Dao classes.
        for endpoint in self.app.endpoints.values():
            endpoint.target.__globals__.update(self.types.biz)
            endpoint.target.__globals__.update(self.types.dal)
            endpoint.target.__globals__.update(
                {p.name: p.target
                 for p in self.app.endpoints.values()}
            )

    def bind(self, rebind=False):
        self.app.binder.bind(rebind=rebind)

    def _discover_pybiz_classes(self, namespace: Dict):
        # package name for venusian scan
        self._scan_venusian()
        if namespace:
            # load BizObject and Dao classes from a namespace dict
            self._scan_namespace(namespace)

        # load BizObject and Dao classes from dotted path strings in bindings
        self._scan_dotted_paths()

        # remove base BizObject class from types dict
        self.types.biz.pop('BizObject', None)
        self.types.dal.pop('Dao', None)

    def _register_dao_classes(self):
        """
        Associate each BizObject class with a corresponding Dao class.
        """
        # register each binding declared in the manifest with the ApplicationDaoBinder
        for info in self.bindings:
            biz_class = self.types.biz.get(info.biz)
            if biz_class is None:
                raise ManifestError(
                    f'cannot register {info.biz} with ApplicationDaoBinder because '
                    f'the class was not found while processing the manifest'
                )
            dao_class = self.types.dal[info.dao]
            if not self.app.binder.is_registered(biz_class):
                binding = self.app.binder.register(
                    biz_class=biz_class,
                    dao_class=dao_class,
                    dao_bind_kwargs=info.params,
                )
                self.types.dal[info.dao] = binding.dao_class

        # register all dao types *not* currently declared in a binding
        # with the ApplicationDaoBinder.
        for type_name, dao_class in self.types.dal.items():
            if not self.app.binder.get_dao_class(type_name):
                self.app.binder.register(None, dao_class)
                registered_dao_class = self.app.binder.get_dao_class(type_name)
                self.types.dal[type_name] = registered_dao_class

    def _scan_dotted_paths(self):
        # gather Dao and BizObject types in "bindings" section
        # into self.types.dal and self.types.biz
        for binding in self.bindings:
            if binding.biz_module and binding.biz not in self.types.biz:
                biz_class = import_object(f'{binding.biz_module}.{binding.biz}')
                self.types.biz[binding.biz] = biz_class
            if binding.dao_module and binding.dao not in self.types.dal:
                dao_class = import_object(f'{binding.dao_module}.{binding.dao}')
                self.types.dal[binding.dao] = dao_class

        # gather Dao types in "bootstraps" section into self.types.dal
        for dao_class_name, bootstrap in self.bootstraps.items():
            if '.' in bootstrap.dao:
                dao_class_path = bootstrap.dao
                if dao_class_name not in self.types.dal:
                    dao_class = import_object(dao_class_path)
                    self.types.dal[dao_class_name] = dao_class
            elif bootstrap.dao not in self.types.dal:
                raise ManifestError(f'{bootstrap.dao} not found')

    def _scan_namespace(self, namespace: Dict):
        """
        Populate self.types from namespace dict.
        """
        from pybiz.dao import Dao
        from pybiz.biz import BizObject

        for k, v in (namespace or {}).items():
            if isinstance(v, type):
                if issubclass(v, BizObject) and v is not BizObject:
                    self.types.biz[k] = v
                    console.debug(
                        f'detected BizObject class in '
                        f'namespace dict: {v.__name__}'
                    )
                elif issubclass(v, Dao):
                    self.types.dal[k] = v
                    console.debug(
                        f'detected Dao class in namespace '
                        f'dict: {v.__name__}'
                    )

    def _scan_venusian(self):
        """
        Use venusian simply to scan the endpoint packages/modules, causing the
        endpoint callables to register themselves with the Application instance.
        """
        import pybiz.dao
        import pybiz.contrib

        def on_error(name):
            from pybiz.util.loggers import console

            exc_str = traceback.format_exc()
            console.debug(
                message=f'venusian scan failed for {name}',
                data={'trace': exc_str.split('\n')}
            )

        console.debug('venusian scan for BizType and Dao types initiated')

        self.scanner.scan(pybiz.dao, onerror=on_error)
        self.scanner.scan(pybiz.contrib, onerror=on_error)

        pkg_path = self.package
        if pkg_path:
            pkg = importlib.import_module(pkg_path)
            self.scanner.scan(pkg, onerror=on_error)

    @staticmethod
    def _expand_environment_vars(env, data):
        """
        Replace all environment variables used as keys or values in the manifest
        data dict. These are string like `$my_env_var`.
        """
        re_env_var = re.compile(r'^\$([\w\-]+)$')

        def expand(data):
            if isinstance(data, str):
                match = re_env_var.match(data)
                if match:
                    var_name = match.groups()[0]
                    return env[var_name]
                else:
                    return data
            elif isinstance(data, list):
                return [expand(x) for x in data]
            elif isinstance(data, dict):
                for k, v in list(data.items()):
                    if isinstance(k, str):
                        match = re_env_var.match(k)
                        if match:
                            data.pop(k)
                            k_new = match.groups()[0]
                            data[k_new] = v
                    data[k] = expand(v)
                return data
            else:
                return data

        return expand(data)


class ManifestBinding(object):
    def __init__(
        self,
        biz: Text,
        dao: Text,
        params: Dict = None,
    ):
        self.dao = dao
        self.params = params

        if '.' in biz:
            self.biz_module, self.biz = os.path.splitext(biz)
            self.biz = self.biz[1:]
        else:
            self.biz_module, self.biz = None, biz

        if '.' in dao:
            self.dao_module, self.dao = os.path.splitext(dao)
            self.dao = self.dao[1:]
        else:
            self.dao_module, self.dao = None, dao

    def __repr__(self):
        return f'<ManifestBinding({self.biz}, {self.dao})>'


class ManifestBootstrap(object):
    def __init__(self, dao: Text, params: Dict = None):
        self.dao = dao
        self.params = params or {}
