import re
import sqlite3
import threading
import time
from functools import wraps

from flask import g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


LOGIN_FAILURES = {}
LOGIN_FAILURES_LOCK = threading.Lock()
LOGIN_FAILURE_WINDOW_SECONDS = 5 * 60
LOGIN_FAILURE_LIMIT = 5


def validate_username(username):
    username = str(username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
        raise ValueError("用户名需为 3-32 位字母、数字、点、短横线或下划线。")
    return username


def validate_password(password):
    password = str(password or "")
    if len(password) < 8 or len(password) > 128:
        raise ValueError("密码长度需为 8-128 位。")
    return password


def register_auth_routes(
    app,
    get_repository,
    error_response,
    public_user,
    app_name,
    app_version,
    audit_event=None,
):
    audit = audit_event or (lambda *args, **kwargs: None)
    def login_failure_key(username):
        return f"{request.remote_addr or 'local'}:{username.lower()}"

    def login_is_rate_limited(key):
        cutoff = time.time() - LOGIN_FAILURE_WINDOW_SECONDS
        with LOGIN_FAILURES_LOCK:
            recent = [attempt for attempt in LOGIN_FAILURES.get(key, []) if attempt >= cutoff]
            LOGIN_FAILURES[key] = recent
            return len(recent) >= LOGIN_FAILURE_LIMIT

    def record_login_failure(key):
        with LOGIN_FAILURES_LOCK:
            LOGIN_FAILURES.setdefault(key, []).append(time.time())

    def clear_login_failures(key):
        with LOGIN_FAILURES_LOCK:
            LOGIN_FAILURES.pop(key, None)

    def admin_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.current_user or g.current_user.get("role") != "admin":
                return error_response("admin_required", "需要管理员权限。", 403)
            return view(*args, **kwargs)
        return wrapped

    @app.before_request
    def authenticate_request():
        if app.config.get("AUTH_DISABLED"):
            g.current_user = {
                "id": 0,
                "username": "test-admin",
                "role": "admin",
                "active": True,
            }
            return None

        public_paths = {
            "/health",
            "/login",
            "/setup",
            "/auth/status",
            "/auth/login",
            "/auth/setup",
        }
        if request.path.startswith("/static/") or request.path in public_paths:
            g.current_user = None
            return None

        repository = get_repository()
        if repository.user_count() == 0:
            if request.method == "GET" and request.path in ("/", "/studio", "/admin"):
                return redirect(url_for("setup_page"))
            return error_response("setup_required", "请先创建管理员账户。", 428)

        user_id = session.get("user_id")
        user = repository.get_user(user_id) if user_id else None
        if not user or not user.get("active"):
            session.clear()
            g.current_user = None
            if request.method == "GET" and request.path in ("/", "/studio", "/admin"):
                return redirect(url_for("login_page"))
            return error_response("authentication_required", "请先登录。", 401)

        g.current_user = user
        session.permanent = True
        return None

    @app.route('/setup')
    def setup_page():
        if get_repository().user_count() > 0:
            return redirect(url_for("login_page"))
        return render_template(
            "auth.html",
            mode="setup",
            app_name=app_name,
            app_version=app_version,
        )

    @app.route('/login')
    def login_page():
        if get_repository().user_count() == 0:
            return redirect(url_for("setup_page"))
        return render_template(
            "auth.html",
            mode="login",
            app_name=app_name,
            app_version=app_version,
        )

    @app.route('/auth/status')
    def auth_status():
        repository = get_repository()
        user_id = session.get("user_id")
        user = repository.get_user(user_id) if user_id else None
        return jsonify({
            "setup_required": repository.user_count() == 0,
            "authenticated": bool(user and user.get("active")),
            "user": public_user(user) if user and user.get("active") else None,
        })

    @app.route('/auth/setup', methods=['POST'])
    def auth_setup():
        repository = get_repository()
        if repository.user_count() > 0:
            return error_response("setup_completed", "管理员账户已经创建。", 409)
        data = request.get_json(silent=True) or request.form
        try:
            username = validate_username(data.get("username"))
            password = validate_password(data.get("password"))
        except ValueError as error:
            return error_response("invalid_credentials", str(error), 400)
        user = repository.create_user(
            username,
            generate_password_hash(password),
            "admin",
            time.time(),
        )
        session.clear()
        session["user_id"] = user["id"]
        app.logger.info("user_setup user_id=%s username=%s", user["id"], user["username"])
        audit("user_setup", actor_id=user["id"], user_id=user["id"], username=user["username"])
        return jsonify({"user": public_user(user)}), 201

    @app.route('/auth/login', methods=['POST'])
    def auth_login():
        data = request.get_json(silent=True) or request.form
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "")
        failure_key = login_failure_key(username)
        if login_is_rate_limited(failure_key):
            audit("login_rate_limited", username=username)
            return error_response(
                "login_rate_limited",
                "登录失败次数过多，请 5 分钟后重试。",
                429,
            )
        user = get_repository().get_user_by_username(username)
        if not user or not user.get("active") or not check_password_hash(user["password_hash"], password):
            record_login_failure(failure_key)
            audit("login_failed", username=username)
            return error_response("invalid_login", "用户名或密码不正确。", 401)
        clear_login_failures(failure_key)
        now = time.time()
        get_repository().mark_login(user["id"], now)
        user["last_login_at"] = now
        session.clear()
        session["user_id"] = user["id"]
        app.logger.info("user_login user_id=%s username=%s", user["id"], user["username"])
        audit("user_login", actor_id=user["id"], user_id=user["id"], username=user["username"])
        return jsonify({"user": public_user(user)})

    @app.route('/auth/logout', methods=['POST'])
    def auth_logout():
        user_id = session.get("user_id")
        session.clear()
        app.logger.info("user_logout user_id=%s", user_id)
        audit("user_logout", actor_id=user_id, user_id=user_id)
        return jsonify({"logged_out": True})

    @app.route('/auth/me')
    def auth_me():
        return jsonify({"user": public_user(g.current_user)})

    @app.route('/admin')
    @admin_required
    def admin_page():
        return render_template(
            "admin.html",
            app_name=app_name,
            app_version=app_version,
            current_user=public_user(g.current_user),
        )

    @app.route('/admin/users')
    @admin_required
    def admin_users():
        return jsonify([public_user(user) for user in get_repository().list_users()])

    @app.route('/admin/users', methods=['POST'])
    @admin_required
    def admin_create_user():
        data = request.get_json(silent=True) or {}
        try:
            username = validate_username(data.get("username"))
            password = validate_password(data.get("password"))
        except ValueError as error:
            return error_response("invalid_user", str(error), 400)
        role = data.get("role", "user")
        if role not in ("admin", "user"):
            return error_response("invalid_role", "用户角色无效。", 400)
        try:
            user = get_repository().create_user(
                username,
                generate_password_hash(password),
                role,
                time.time(),
            )
        except sqlite3.IntegrityError:
            return error_response("username_exists", "用户名已存在。", 409)
        app.logger.info(
            "user_created actor=%s user_id=%s role=%s",
            g.current_user["id"],
            user["id"],
            role,
        )
        audit(
            "user_created",
            user_id=user["id"],
            username=user["username"],
            role=role,
        )
        return jsonify({"user": public_user(user)}), 201

    @app.route('/admin/users/<int:user_id>', methods=['PATCH'])
    @admin_required
    def admin_update_user(user_id):
        repository = get_repository()
        user = repository.get_user(user_id)
        if not user:
            return error_response("user_not_found", "用户不存在。", 404)
        data = request.get_json(silent=True) or {}
        role = data.get("role")
        active = data.get("active")
        password = data.get("password")
        if role is not None and role not in ("admin", "user"):
            return error_response("invalid_role", "用户角色无效。", 400)
        if password is not None:
            try:
                password = validate_password(password)
            except ValueError as error:
                return error_response("invalid_password", str(error), 400)
        active_admins = [
            item for item in repository.list_users()
            if item["role"] == "admin" and item["active"]
        ]
        removes_admin = (
            user["role"] == "admin"
            and user["active"]
            and (role == "user" or active is False)
        )
        if removes_admin and len(active_admins) <= 1:
            return error_response("last_admin_required", "至少需要保留一个启用的管理员。", 409)
        updated_user = repository.update_user(
            user_id,
            role=role,
            active=active,
            password_hash=generate_password_hash(password) if password is not None else None,
            now=time.time(),
        )
        if user_id == g.current_user["id"] and active is False:
            session.clear()
        app.logger.info(
            "user_updated actor=%s user_id=%s role=%s active=%s password_reset=%s",
            g.current_user["id"],
            user_id,
            role,
            active,
            password is not None,
        )
        audit(
            "user_updated",
            user_id=user_id,
            role=role,
            active=active,
            password_reset=password is not None,
        )
        return jsonify({"user": public_user(updated_user)})
