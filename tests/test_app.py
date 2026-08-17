import os
import tempfile
import unittest
from datetime import date

from werkzeug.security import generate_password_hash

from app import app, get_db, init_db, score_guess


class GuessTheWordTests(unittest.TestCase):
    def setUp(self):
        self.database = tempfile.NamedTemporaryFile(delete=False).name
        app.config.update(TESTING=True, DATABASE=self.database, SECRET_KEY="test")
        with app.app_context():
            init_db()
        self.client = app.test_client()

    def tearDown(self):
        os.unlink(self.database)

    def register_player(self, username="Alice", password="Pass1$"):
        return self.client.post("/register", data={"username": username, "password": password})

    def login_player(self, username="Alice", password="Pass1$", follow_redirects=False):
        return self.client.post(
            "/login", data={"username": username, "password": password}, follow_redirects=follow_redirects
        )

    def create_admin(self, username="AdminUser", password="Admin1$"):
        with app.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                (username, generate_password_hash(password)),
            )
            db.commit()

    def start_game_with_word(self, username, answer):
        with app.app_context():
            db = get_db()
            user = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            word = db.execute("SELECT id FROM words WHERE value = ?", (answer,)).fetchone()
            db.execute(
                "INSERT INTO games (user_id, word_id, started_on) VALUES (?, ?, ?)",
                (user["id"], word["id"], date.today().isoformat()),
            )
            db.commit()
            return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_scoring_handles_duplicate_letters(self):
        self.assertEqual(score_guess("ALLEY", "APPLE"), ["correct", "present", "absent", "present", "absent"])

    def test_registration_requires_valid_password(self):
        response = self.client.post("/register", data={"username": "Alice", "password": "plain"}, follow_redirects=True)
        self.assertIn(b"Password must", response.data)

    def test_registration_requires_mixed_case_username(self):
        for username in ("alice", "ALICE", "aaaaa"):
            response = self.client.post(
                "/register", data={"username": username, "password": "Pass1$"}, follow_redirects=True
            )
            self.assertIn(b"Username must", response.data, msg=f"Expected rejection for {username}")

    def test_register_and_login(self):
        self.register_player()
        response = self.login_player(follow_redirects=True)
        self.assertIn(b"Ready for a new word", response.data)

    def test_player_can_submit_a_guess(self):
        self.register_player()
        self.login_player()
        self.client.post("/games")
        response = self.client.post("/games/1/guess", data={"guess": "APPLE"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A", response.data)

    def test_win_shows_board_and_ok_before_next_game(self):
        self.register_player()
        self.login_player()
        game_id = self.start_game_with_word("Alice", "APPLE")
        response = self.client.post(f"/games/{game_id}/guess", data={"guess": "APPLE"}, follow_redirects=True)
        self.assertIn(b"Congratulations", response.data)
        self.assertIn(b"OK", response.data)
        self.assertNotIn(b"Ready for a new word", response.data)

        response = self.client.post(f"/games/{game_id}/acknowledge", follow_redirects=True)
        self.assertIn(b"Ready for a new word", response.data)

    def test_loss_shows_board_and_ok_with_answer(self):
        self.register_player()
        self.login_player()
        game_id = self.start_game_with_word("Alice", "APPLE")
        wrong = ["BRICK", "CLOUD", "DREAM", "EARTH", "FLAME"]
        for guess in wrong:
            response = self.client.post(f"/games/{game_id}/guess", data={"guess": guess}, follow_redirects=True)
        self.assertIn(b"Better luck next time", response.data)
        self.assertIn(b"APPLE", response.data)
        self.assertIn(b"OK", response.data)

        response = self.client.post(f"/games/{game_id}/acknowledge", follow_redirects=True)
        self.assertIn(b"Ready for a new word", response.data)

    def test_cannot_start_second_game_while_one_is_active(self):
        self.register_player()
        self.login_player()
        self.client.post("/games")
        with app.app_context():
            count_before = get_db().execute("SELECT COUNT(*) FROM games").fetchone()[0]
        self.client.post("/games")
        with app.app_context():
            count_after = get_db().execute("SELECT COUNT(*) FROM games").fetchone()[0]
        self.assertEqual(count_before, count_after)

    def test_daily_limit_blocks_fourth_game(self):
        self.register_player()
        self.login_player()
        for answer in ("APPLE", "BEACH", "BRAIN"):
            game_id = self.start_game_with_word("Alice", answer)
            self.client.post(f"/games/{game_id}/guess", data={"guess": answer})
            self.client.post(f"/games/{game_id}/acknowledge")
        response = self.client.post("/games", follow_redirects=True)
        self.assertIn(b"limit of 3 words", response.data)

    def test_admin_reports_show_daily_and_player_stats(self):
        self.create_admin()
        self.register_player("Alice")
        self.login_player("Alice")
        game_id = self.start_game_with_word("Alice", "APPLE")
        self.client.post(f"/games/{game_id}/guess", data={"guess": "APPLE"})
        self.client.post(f"/games/{game_id}/acknowledge")

        self.client.get("/logout")
        self.client.post("/login", data={"username": "AdminUser", "password": "Admin1$"})
        today = date.today().isoformat()
        response = self.client.get(f"/admin/reports?day={today}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Unique players", response.data)
        self.assertIn(b"Correct guesses", response.data)
        self.assertIn(b"Alice", response.data)
        self.assertIn(today.encode(), response.data)


if __name__ == "__main__":
    unittest.main()
