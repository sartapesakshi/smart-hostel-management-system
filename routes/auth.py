"""Authentication: first-run setup, login, logout (sessions + hashed passwords)."""
from flask import (Blueprint, flash, g, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
import helpers
from helpers import clean

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    return redirect(url_for("dashboard.index" if session.get("user_id") else "auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if db.scalar("SELECT COUNT(*) FROM users") == 0:
        return redirect(url_for("auth.setup"))
    if g.user:
        return redirect(url_for("dashboard.index"))

    next_url = helpers.safe_next_url(request.values.get("next"))
    error = None
    username = ""
    if request.method == "POST":
        username = clean(request.form.get("username"))
        password = request.form.get("password", "")
        if not username or not password:
            error = "Please enter both username and password."
        else:
            user = db.query_one("SELECT * FROM users WHERE username = ?", (username,))
            # same message for "no such user" and "wrong password" - do not reveal which
            if user is None or not check_password_hash(user["password_hash"], password):
                error = "Invalid username or password."
            else:
                session.clear()                      # new session after login (prevents fixation)
                session["user_id"] = user["id"]
                session.permanent = request.form.get("remember") == "on"
                database = db.get_db()
                database.execute("UPDATE users SET last_login = datetime('now','localtime') WHERE id = ?",
                                 (user["id"],))
                database.commit()
                flash(f"Welcome back, {user['full_name']}.", "success")
                return redirect(next_url or url_for("dashboard.index"))
    return render_template("login.html", error=error, username=username, next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    """Shown only while the users table is empty: creates the first administrator."""
    if db.scalar("SELECT COUNT(*) FROM users") > 0:
        return redirect(url_for("auth.login"))

    errors, form = {}, {}
    if request.method == "POST":
        form = {k: clean(request.form.get(k)) for k in ("username", "full_name", "email")}
        password = request.form.get("password", "")
        if not helpers.USERNAME_RE.fullmatch(form["username"]):
            errors["username"] = "3-30 characters: letters, numbers, dot or underscore."
        if not helpers.valid_person_name(form["full_name"]):
            errors["full_name"] = "Enter the administrator's full name."
        if form["email"] and not helpers.valid_email(form["email"]):
            errors["email"] = "Enter a valid email address."
        problem = helpers.password_problem(password)
        if problem:
            errors["password"] = problem
        elif password != request.form.get("confirm", ""):
            errors["confirm"] = "Passwords do not match."
        if not errors:
            database = db.get_db()
            database.execute(
                "INSERT INTO users (username, password_hash, full_name, email) VALUES (?,?,?,?)",
                (form["username"], generate_password_hash(password), form["full_name"],
                 form["email"] or None))
            database.commit()
            flash("Administrator account created. Please log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("setup.html", errors=errors, form=form)
