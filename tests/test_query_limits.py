from fastapi.routing import APIRoute

from alac_rip.server import app


def _route(path: str) -> APIRoute:
    return next(route for route in app.routes if isinstance(route, APIRoute) and route.path == path)


def test_sync_history_routes_bound_the_limit_query_parameter():
    for path in ("/sync-history", "/sync-history/{name}"):
        route = _route(path)
        limit = next(parameter for parameter in route.dependant.query_params if parameter.name == "limit")
        constraints = {
            attribute: getattr(constraint, attribute)
            for constraint in limit.field_info.metadata
            for attribute in ("ge", "le")
            if hasattr(constraint, attribute)
        }

        assert constraints == {"ge": 1, "le": 100}
