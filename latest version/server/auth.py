import base64
from functools import wraps

from core.config_manager import Config
from core.error import ArcError, NoAccess
from core.sql import Connect
from core.user import UserAuth, UserLogin
from flask import Blueprint, g, jsonify, request

from .func import arc_try, error_return

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['POST'])  # 登录接口
@arc_try
def login():
    headers = request.headers
    if Config.ALLOW_APPVERSION:  # 版本检查
        if 'AppVersion' not in headers or headers['AppVersion'] not in Config.ALLOW_APPVERSION:
            raise NoAccess('Invalid app version.', 1203)

    request.form['grant_type']
    with Connect() as c:
        id_pwd = headers['Authorization']
        id_pwd = base64.b64decode(id_pwd[6:]).decode()
        name, password = id_pwd.split(':', 1)
        if 'DeviceId' in headers:
            device_id = headers['DeviceId']
        else:
            device_id = 'low_version'

        user = UserLogin(c)
        user.login(name, password, device_id, request.remote_addr)

        return jsonify({"success": True, "token_type": "Bearer", 'user_id': user.user_id, 'access_token': user.token})


def auth_required(request):
    # arcaea登录验证，写成了修饰器
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):

            headers = request.headers

            if Config.ALLOW_APPVERSION:  # 版本检查
                if 'AppVersion' not in headers or headers['AppVersion'] not in Config.ALLOW_APPVERSION:
                    return error_return(NoAccess('Invalid app version.', 1203))

            with Connect() as c:
                try:
                    user = UserAuth(c)
                    token = headers.get('Authorization')
                    if not token:
                        raise NoAccess('No token.', -4)
                    user.token = token[7:]
                    user_id = user.token_get_id()
                    g.user = user
                except ArcError as e:
                    return error_return(e)
            return view(user_id, *args, **kwargs)

        return wrapped_view
    return decorator
