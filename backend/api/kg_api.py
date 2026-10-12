"""知识图谱接口的路由挂载点。

图谱的接口实现都在 kg/api.py（和 rag 包一样，能力放在自己的包里），
这里只做一层导出，让 main.py 的 import 风格和其它模块保持一致：
    from api.kg_api import router as kg_router
"""

from kg.api import router

__all__ = ["router"]
