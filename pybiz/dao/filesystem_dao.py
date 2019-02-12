import os
import uuid
import glob

from typing import Text, List, Set, Dict, Tuple
from collections import defaultdict
from datetime import datetime

from appyratus.utils import (
    DictAccessor,
    DictUtils,
    StringUtils,
)
from appyratus.files import BaseFile, Yaml

from pybiz.util import import_object

from .base import Dao
from .python_dao import PythonDao


class FilesystemDao(Dao):
    def __init__(
        self,
        root: Text,
        ftype: Text = None,
        extensions: Set[Text] = None,
    ):
        super().__init__()

        # convert the ftype string arg into a File class ref
        if not ftype:
            self.ftype = Yaml
        elif not isinstance(ftype, BaseFile):
            self.ftype = import_object(ftype)

        assert issubclass(self.ftype, BaseFile)

        # self.paths is where we store named file paths
        self.paths = DictAccessor({'root': root})

        # set of recognized (case-normalized) file extensions
        self.extensions = {
            ext.lower() for ext in (
                extensions or self.ftype.extensions()
            )
        }
        if extensions:
            self.extensions.update(extensions)

    def bind(self, biz_type):
        """
        Ensure the data dir exists for this BizObject type.
        """
        super().bind(biz_type)
        self.paths.data = os.path.join(
            self.paths.root, StringUtils.snake(biz_type.__name__)
        )
        os.makedirs(self.paths.data, exist_ok=True)

    def create_id(self, record):
        return record.get('_id', uuid.uuid4().hex)

    def exists(self, fname: Text) -> bool:
        return BaseFile.exists(self.mkpath(fname))

    def create(self, record: Dict) -> Dict:
        _id = self.create_id(record)
        record = self.update(_id, record)
        record['_id'] = _id
        return record

    def create_many(self, records):
        for record in records:
            self.create(record)

    def count(self) -> int:
        running_count = 0
        for ext in self.extensions:
            fnames = glob.glob(f'{self.paths.data}/*.{ext}')
            running_count += len(fnames)
        return running_count

    def fetch(self, _id, fields=None) -> Dict:
        records = self.fetch_many([_id], fields=fields)
        return records.get(_id) if records else None

    def fetch_many(self, _ids: List, fields: List = None) -> Dict:
        if not _ids:
            _ids = self._fetch_all_ids()

        fields = fields if isinstance(fields, set) else set(fields or [])
        if not fields:
            fields = set(self.biz_type.schema.fields.keys())
        fields |= {'_id', '_rev'}

        records = {}

        for _id in _ids:
            fpath = self.mkpath(_id)
            record = self.ftype.from_file(fpath)
            if record:
                record.setdefault('_id', _id)
                record['_rev'] = record.setdefault('_rev', 0)
                records[_id] = {k: record[k] for k in fields}
            else:
                records['_id'] = None

        return records

    def fetch_all(self, fields: Set[Text] = None) -> Dict:
        return self.fetch_many(None, fields=fields)

    def update(self, _id, data: Dict) -> Dict:
        if not self.exists(_id):
            # this is here, because update in this dao is can be used like #
            # upsert, but in the BizObject class, insert_defaults is only called
            # on create, not update.
            self.biz_type.insert_defaults(data)

        fpath = self.mkpath(_id)
        base_record = self.ftype.from_file(fpath)
        if base_record:
            # this is an upsert
            record = DictUtils.merge(base_record, data)
        else:
            record = data

        if '_id' not in record:
            record['_id'] = _id

        if '_rev' not in record:
            record['_rev'] = 0
        else:
            record['_rev'] += 1

        self.ftype.to_file(file_path=fpath, data=record)
        return record

    def update_many(self, _ids: List, updates: List = None) -> Dict:
        return {
            _id: self.update(_id, data)
            for _id, data in zip(_ids, update)
        }

    def delete(self, _id) -> None:
        fpath = self.mkpath(_id)
        os.unlink(fpath)

    def delete_many(self, _ids: List) -> None:
        for _id in _ids:
            self.delete(_id)

    def delete_all(self):
        _ids = self._fetch_all_ids()
        self.delete_many(_ids)

    def query(self, predicate: 'Predicate', **kwargs):
        return []  # not implemented

    def mkpath(self, fname: Text) -> Text:
        fname = self.ftype.format_file_name(fname)
        return os.path.join(self.paths.data, fname)

    def _fetch_all_ids(self):
        _ids = set()
        for ext in self.extensions:
            for fname in glob.glob(f'{self.paths.data}/*.{ext}'):
                base = fname.split('.')[0]
                _ids.add(os.path.basename(base))
        return _ids
