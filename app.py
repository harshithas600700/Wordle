import os
import random
import re
import sqlite3
from datetime import date
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "replace-this-secret-before-production"),
    DATABASE=os.environ.get("DATABASE", os.path.join(app.root_path, "guess_the_word.db")),
)
app.jinja_env.globals.update(zip=zip)

WORDS = [
    "APPLE", "BEACH", "BRAIN", "BREAD", "BRICK", "CLOUD", "DREAM", "EARTH", "FLAME", "GRAPE",
    "HOUSE", "LEMON", "MANGO", "MONEY", "MUSIC", "OCEAN", "PLANT", "RIVER", "SMILE", "TIGER",
]
USERNAME_PATTERN = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])[A-Za-z]{5,}$")
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)(?=.*[$%*]).{5,}$")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('player', 'admin'))
        );
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY, value TEXT NOT NULL UNIQUE CHECK(length(value) = 5)
        );
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, word_id INTEGER NOT NULL,
            started_on TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', guesses_used INTEGER NOT NULL DEFAULT 0,
            acknowledged INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(word_id) REFERENCES words(id)
        );
        CREATE TABLE IF NOT EXISTS guesses (
            id INTEGER PRIMARY KEY, game_id INTEGER NOT NULL, value TEXT NOT NULL,
            guessed_on TEXT NOT NULL, FOREIGN KEY(game_id) REFERENCES games(id)
        );
    """)
    db.executemany("INSERT OR IGNORE INTO words (value) VALUES (?)", [(word,) for word in WORDS])
    try:
        db.execute("ALTER TABLE games ADD COLUMN acknowledged INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    db.commit()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access is required.", "error")
            return redirect(url_for("play"))
        return view(*args, **kwargs)
    return wrapped


def score_guess(guess, answer):
    """Return Wordle-style statuses while accounting for repeated letters."""
    result = ["absent"] * 5
    remaining = list(answer)
    for index, letter in enumerate(guess):
        if letter == answer[index]:
            result[index] = "correct"
            remaining[index] = None
    for index, letter in enumerate(guess):
        if result[index] == "absent" and letter in remaining:
            result[index] = "present"
            remaining[remaining.index(letter)] = None
    return result


def game_row(game_id):
    return get_db().execute("""
        SELECT games.*, words.value AS answer FROM games JOIN words ON words.id = games.word_id
        WHERE games.id = ?
    """, (game_id,)).fetchone()


@app.route("/")
def index():
    return redirect(url_for("admin_reports" if session.get("role") == "admin" else "play")) if "user_id" in session else redirect(url_for("login"))


@app.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not USERNAME_PATTERN.fullmatch(username):
            flash("Username must have at least 5 letters, contain only letters, and include both upper and lower case.", "error")
        elif not PASSWORD_PATTERN.fullmatch(password):
            flash("Password must be at least 5 characters with a letter, number, and one of $, %, or *.", "error")
        else:
            try:
                db = get_db()
                db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'player')",
                           (username, generate_password_hash(password)))
                db.commit()
                flash("Account created. Please log in.", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That username is already in use.", "error")
    return render_template("register.html")


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (request.form.get("username", "").strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], username=user["username"], role=user["role"])
            return redirect(url_for("admin_reports" if user["role"] == "admin" else "play"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/play")
@login_required
def play():
    if session.get("role") == "admin":
        return redirect(url_for("admin_reports"))
    db = get_db()
    today = date.today().isoformat()
    games_today = db.execute("SELECT COUNT(*) FROM games WHERE user_id = ? AND started_on = ?", (session["user_id"], today)).fetchone()[0]
    game = db.execute("""
        SELECT id FROM games WHERE user_id = ?
        AND (status = 'active' OR (status IN ('won', 'lost') AND acknowledged = 0))
        ORDER BY id DESC LIMIT 1
    """, (session["user_id"],)).fetchone()
    return render_template("play.html", game=game_row(game["id"]) if game else None, games_today=games_today, rows=game_guesses(game["id"]) if game else [])


@app.post("/games")
@login_required
def start_game():
    if session.get("role") == "admin":
        return redirect(url_for("admin_reports"))
    db = get_db()
    today = date.today().isoformat()
    in_progress = db.execute("""
        SELECT id FROM games WHERE user_id = ?
        AND (status = 'active' OR (status IN ('won', 'lost') AND acknowledged = 0))
    """, (session["user_id"],)).fetchone()
    played = db.execute("SELECT COUNT(*) FROM games WHERE user_id = ? AND started_on = ?", (session["user_id"], today)).fetchone()[0]
    if in_progress:
        return redirect(url_for("play"))
    if played >= 3:
        flash("You have reached today’s limit of 3 words.", "error")
        return redirect(url_for("play"))
    word = db.execute("SELECT id FROM words ORDER BY RANDOM() LIMIT 1").fetchone()
    db.execute("INSERT INTO games (user_id, word_id, started_on) VALUES (?, ?, ?)", (session["user_id"], word["id"], today))
    db.commit()
    return redirect(url_for("play"))


def game_guesses(game_id):
    game = game_row(game_id)
    guesses = get_db().execute("SELECT value FROM guesses WHERE game_id = ? ORDER BY id", (game_id,)).fetchall()
    return [(item["value"], score_guess(item["value"], game["answer"])) for item in guesses]


@app.post("/games/<int:game_id>/guess")
@login_required
def submit_guess(game_id):
    game = game_row(game_id)
    if not game or game["user_id"] != session["user_id"] or game["status"] != "active":
        flash("That game is not available.", "error")
        return redirect(url_for("play"))
    guess = request.form.get("guess", "").strip().upper()
    if not re.fullmatch(r"[A-Z]{5}", guess):
        flash("Enter exactly five English letters.", "error")
        return redirect(url_for("play"))
    db = get_db()
    db.execute("INSERT INTO guesses (game_id, value, guessed_on) VALUES (?, ?, ?)", (game_id, guess, date.today().isoformat()))
    used = game["guesses_used"] + 1
    status = "won" if guess == game["answer"] else "lost" if used == 5 else "active"
    db.execute("UPDATE games SET guesses_used = ?, status = ? WHERE id = ?", (used, status, game_id))
    db.commit()
    return redirect(url_for("play"))


@app.post("/games/<int:game_id>/acknowledge")
@login_required
def acknowledge_game(game_id):
    game = game_row(game_id)
    if not game or game["user_id"] != session["user_id"]:
        flash("That game is not available.", "error")
        return redirect(url_for("play"))
    if game["status"] not in ("won", "lost") or game["acknowledged"]:
        return redirect(url_for("play"))
    db = get_db()
    db.execute("UPDATE games SET acknowledged = 1 WHERE id = ?", (game_id,))
    db.commit()
    return redirect(url_for("play"))


@app.route("/admin/reports")
@admin_required
def admin_reports():
    db = get_db()
    day = request.args.get("day", date.today().isoformat())
    daily = db.execute("""
        SELECT COUNT(DISTINCT user_id) AS users, SUM(status = 'won') AS wins FROM games WHERE started_on = ?
    """, (day,)).fetchone()
    players = db.execute("""
        SELECT users.username, games.started_on, COUNT(*) AS tried, SUM(games.status = 'won') AS wins
        FROM games
        JOIN users ON users.id = games.user_id
        WHERE users.role = 'player'
        GROUP BY users.id, users.username, games.started_on
        ORDER BY games.started_on DESC, users.username ASC
    """).fetchall()
    return render_template("reports.html", day=day, daily=daily, players=players)


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Database initialized with 20 words.")


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True)
