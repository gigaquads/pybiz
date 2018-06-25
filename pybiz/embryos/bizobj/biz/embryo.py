from appyratus.validation import Schema, fields as schema_fields
from embryo.embryo import Embryo


class BizEmbryo(Embryo):
    """
    # Biz Embryo
    """

    class context_schema(Schema):
        """
        # Context Schema
        The respective Biz schema

        ## Fields
        * `project_name`: TODO
        * `name`: TODO
        * `fields`: TODO
        """
        project_name = schema_fields.Str()
        name = schema_fields.Str()
        fields = schema_fields.List(nested=schema_fields.Dict())
