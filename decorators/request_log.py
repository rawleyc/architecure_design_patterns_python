from datetime import datetime
from functools import wraps

from flask import request

from singletons.requests import Requests


def request_log(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        stats = Requests.get_instance()
        stats.count += 1
        stats.last_path = request.path
        started = datetime.now()

        try:
            result = view(*args, **kwargs)
            return result

        finally:
            stats.last_seconds = (datetime.now() - started).total_seconds()
            print("request", stats.count, request.path, stats.last_seconds)

    return wrapper
