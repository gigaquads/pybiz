from pybiz.dao.zodb_dao import ZodbDao

from .base import Middleware


class ZodbDaoMiddleware(Middleware):
    def __init__(self):
        super().__init__()

    def bind(self, service):
        ZodbDao.connect(service.env['ZODB_DATA_FILE'])

    def process_request(self, request, response):
        pass

    def process_resource(self, request, response, resource, params):
        pass

    def process_response(self, request, response, resource):
        status_code = int(response.status[:3])
        if 200 <= status_code < 300:
            try:
                ZodbDao.commit()
            except Exception:
                ZodbDao.rollback()
        else:
            ZodbDao.rollback()
